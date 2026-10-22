"""Host / Origin 校验（防 DNS rebinding）：真的起服务（临时端口、临时库），用 socket 手送请求自订 Host。
    python -m unittest tests.test_hostcheck
"""
import base64
import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.server import launch
from easyread.server import server

TITLE = "SecretTitleQ7Zx"
MINI_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
_MISSING = object()


def raw(port: int, method: str, path: str, host=_MISSING, headers: dict | None = None, body: bytes = b""):
    """手写 HTTP/1.1 请求：host 为 _MISSING 时不带 Host 标头。返回 (状态码, 标头原文, 内文)。"""
    lines = [f"{method} {path} HTTP/1.1"]
    if host is not _MISSING:
        lines.append(f"Host: {host}")
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    if body:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: close")
    data = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(data)
        chunks = []
        while True:
            c = s.recv(65536)
            if not c:
                break
            chunks.append(c)
    resp = b"".join(chunks)
    head, _, content = resp.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), head.decode("latin-1"), content


class HostCheckBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": cls.tmp.name})
        cls.env.start()
        cls.cfg = patch.object(server.config, "CONFIG_PATH", Path(cls.tmp.name) / "no-config.json")  # 不碰真实 config.json
        cls.cfg.start()
        cls.app = server.App(server.config.load())
        server.Handler.app = cls.app
        cls.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        ws, _ = cls.app.lib.create_from_pdf(MINI_PDF, "x.pdf", {"title_en": TITLE})
        cls.pid = ws.id
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.cfg.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    @property
    def token(self):
        return self.app.token

    def good_host(self):
        return f"127.0.0.1:{self.port}"

    def assert_blocked(self, status, content, head=""):
        self.assertEqual(status, 403, (head, content))
        text = content.decode("utf-8", "replace")
        self.assertNotIn(self.token, text)
        self.assertNotIn(TITLE, text)
        self.assertNotIn(self.pid, text)
        self.assertIn('"error"', text)


class GoodHostTest(HostCheckBase):
    def test_legit_hosts_get(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LocalHost:{self.port}"):
            for path in ("/", "/api/library"):
                status, head, content = raw(self.port, "GET", path, host)
                self.assertEqual(status, 200, (host, path, head))
            self.assertIn(self.token, raw(self.port, "GET", "/api/library", host)[2].decode())

    def test_legit_ipv6_host_header(self):
        # 服务只绑 IPv4，这里不用 [::1] 连线，只验证带 [::1] Host 标头的请求会被接受
        status, *_ = raw(self.port, "GET", "/api/library", f"[::1]:{self.port}")
        self.assertEqual(status, 200)

    def test_state_with_legit_host(self):
        status, _, content = raw(self.port, "GET", f"/api/p/{self.pid}/state", self.good_host())
        self.assertEqual(status, 200)


class BadHostTest(HostCheckBase):
    def bad_hosts(self):
        p = self.port
        return ["evil.com", f"127.0.0.1:{p}.evil.com", f"localhost.evil.com:{p}", f"127.0.0.1:{p}@evil.com",
                f"127.0.0.1:{p + 1}", f"0.0.0.0:{p}", f"127.1:{p}", f"localhost.:{p}", f"0x7f.1:{p}",
                "127.0.0.1", "localhost", f"attacker.test:{p}", f"127.0.0.1:{p} ", f"127.0.0.1:{p},evil.com", ""]

    def test_get_library_and_state(self):
        for host in self.bad_hosts():
            for path in ("/api/library", f"/api/p/{self.pid}/state", "/"):
                with self.subTest(host=host, path=path):
                    status, head, content = raw(self.port, "GET", path, host)
                    self.assert_blocked(status, content, head)
                    self.assertNotIn("evil", content.decode().lower())  # 不回显攻击者的 Host

    def test_missing_host(self):
        status, head, content = raw(self.port, "GET", "/api/library")
        self.assert_blocked(status, content, head)

    def test_duplicate_host(self):
        status, head, content = raw(self.port, "GET", "/api/library", self.good_host(), {"Host": "evil.com"})
        self.assert_blocked(status, content, head)

    def test_post_with_valid_token_still_blocked(self):
        for host in self.bad_hosts():
            with self.subTest(host=host):
                status, head, content = raw(self.port, "POST", f"/api/p/{self.pid}/item", host,
                                            {"X-Token": self.token, "Content-Type": "application/json"}, b'{"status":"done"}')
                self.assert_blocked(status, content, head)
        self.assertNotEqual(self.app.lib.ws(self.pid).load("item").get("status"), "done")

    def test_head_and_options(self):
        for method in ("HEAD", "OPTIONS", "PUT", "DELETE"):
            for host in ("evil.com", f"127.0.0.1:{self.port}.evil.com"):
                with self.subTest(method=method, host=host):
                    status, head, content = raw(self.port, method, "/api/library", host)
                    self.assertEqual(status, 403, head)
                    self.assertNotIn(self.token.encode(), head.encode() + content)
                    if method == "HEAD":
                        self.assertEqual(content, b"")
                    else:
                        self.assert_blocked(status, content, head)

    def test_http_client_with_custom_host(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("GET", "/api/library", skip_host=True)
        c.putheader("Host", "attacker.test:%d" % self.port)
        c.endheaders()
        r = c.getresponse()
        body = r.read()
        c.close()
        self.assertEqual(r.status, 403)
        self.assertNotIn(self.token.encode(), body)


class OriginTest(HostCheckBase):
    def post(self, origin=None, token=True):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Token"] = self.token
        if origin is not None:
            h["Origin"] = origin
        return raw(self.port, "POST", f"/api/p/{self.pid}/item", self.good_host(), h, b'{"status":"reading"}')

    def test_good_origins_reach_token_flow(self):
        p = self.port
        for origin in (None, f"http://127.0.0.1:{p}", f"http://localhost:{p}", f"http://[::1]:{p}", f"HTTP://LOCALHOST:{p}"):
            with self.subTest(origin=origin):
                status, head, content = self.post(origin)
                self.assertEqual(status, 200, (head, content))
                status, head, content = self.post(origin, token=False)  # 通过 Host/Origin 后仍走原 token 校验
                self.assertEqual(status, 403)
                self.assertIn(b"bad token", content)

    def test_bad_origins(self):
        p = self.port
        for origin in ("http://evil.com", "null", f"http://127.0.0.1:{p}.evil.com", f"https://127.0.0.1:{p}",
                       f"http://127.0.0.1:{p + 1}", f"http://127.0.0.1:{p}/", f"http://localhost.evil.com:{p}", ""):
            with self.subTest(origin=origin):
                status, head, content = self.post(origin)
                self.assert_blocked(status, content, head)
                self.assertNotIn(b"bad token", content)  # 是被 Origin 挡的，不是 token 挡的
                self.assertNotIn(b"evil", content)

    def test_get_with_foreign_origin_not_blocked_by_origin(self):
        # 跨源 GET 读不到内容（浏览器 CORS 会拦），且 Host 已验过；Origin 规则只管会改状态的方法和 WebSocket
        status, *_ = raw(self.port, "GET", "/api/library", self.good_host(), {"Origin": "http://evil.com"})
        self.assertEqual(status, 200)


def ws_handshake(port, host, origin=None):
    key = base64.b64encode(os.urandom(16)).decode()
    headers = {"Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Key": key, "Sec-WebSocket-Version": "13"}
    if origin is not None:
        headers["Origin"] = origin
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    lines = ["GET /api/presence HTTP/1.1"] + ([f"Host: {host}"] if host is not _MISSING else []) + [f"{k}: {v}" for k, v in headers.items()]
    s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    return s, s.recv(4096)


class WebSocketTest(HostCheckBase):
    def test_good_host_handshake(self):
        for origin in (None, f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
            with self.subTest(origin=origin):
                s, resp = ws_handshake(self.port, self.good_host(), origin)
                s.close()
                self.assertIn(b" 101 ", resp.split(b"\r\n")[0] + b" ")

    def test_bad_host_rejected(self):
        for host in ("evil.com", f"127.0.0.1:{self.port}.evil.com", f"attacker.test:{self.port}", _MISSING):
            with self.subTest(host=host):
                s, resp = ws_handshake(self.port, host, f"http://{host}" if host is not _MISSING else None)
                s.close()
                self.assertIn(b" 403 ", resp.split(b"\r\n")[0] + b" ")
                self.assertNotIn(self.token.encode(), resp)

    def test_bad_origin_rejected(self):
        for origin in ("http://evil.com", "null", f"http://127.0.0.1:{self.port}.evil.com", f"http://{self.good_host()}.evil.com"):
            with self.subTest(origin=origin):
                s, resp = ws_handshake(self.port, self.good_host(), origin)
                s.close()
                self.assertIn(b" 403 ", resp.split(b"\r\n")[0] + b" ")

    def test_origin_equal_to_attacker_host_rejected(self):
        # 旧逻辑：Origin == http://{Host}，攻击者两边都填自己的域名就能过；现在 Host 先被挡
        s, resp = ws_handshake(self.port, "evil.com", "http://evil.com")
        s.close()
        self.assertIn(b" 403 ", resp.split(b"\r\n")[0] + b" ")


if __name__ == "__main__":
    unittest.main()
