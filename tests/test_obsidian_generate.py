"""Obsidian 生成与 API：只用临时 vault、手写论文及假引擎。"""
from __future__ import annotations

import copy
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from PIL import Image

from easyread import config, engines, launch, obsidian_note, server
from easyread.i18n import tr
from easyread.store import Workspace, write_json_atomic


class GenerateSetup(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        env = patch.dict(os.environ, {"EASYREAD_HOME": str(self.base),
                                     "EASYREAD_LIBRARY": str(self.base / "lib"), "EASYREAD_LANG": "zh-TW"})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg["library_dir"] = str(self.base / "lib")
        self.vault = self.base / "Obsidian Vault"
        self.vault.mkdir()
        self.cfg["obsidian_vault"] = str(self.vault)
        self.root = self.base / "lib" / "paper0001"
        self.root.mkdir(parents=True)
        self.ws = Workspace(self.root)
        self.paper = {"meta": {"title_en": "Paper title", "authors": "Alice", "year": "2026"},
                      "blocks": [{"id": "p1", "type": "paragraph", "page": 1, "en": "Paper evidence"},
                                 {"id": "f1", "type": "figure", "page": 1, "num": 1,
                                  "caption_en": "Architecture", "box": [0, 0, 1, 1]}]}
        write_json_atomic(self.ws.paper_path, self.paper)
        write_json_atomic(self.ws.item_path, {})
        write_json_atomic(self.ws.reader_path, {"notes": {"n1": {"anchor": "p1", "quote": "Evidence"}}})
        Image.new("RGB", (32, 32), "red").save(self.root / "source.pdf", "PDF")
        self.data = {"short": "TEST", "hook": "亮點", "figures": [{"id": "f1", "desc": "架構"}],
                     "diagrams": [{"title": "流程", "mermaid": "graph TD\nA --> B"}]}
        mock = patch("easyread.engines.run", side_effect=lambda *a, **kw: json.dumps(self.data))
        self.run = mock.start()
        self.addCleanup(mock.stop)

    def snapshot(self):
        return {str(p.relative_to(self.vault)): p.read_bytes() if p.is_file() else None
                for p in self.vault.rglob("*")}


class GenerateTest(GenerateSetup):
    def test_generate_writes_note_and_figures_into_vault(self):
        self.data["method"] = "方法重點\n{{fig:f1}}\n{{mark:1}}"
        cancel = threading.Event()
        result = obsidian_note.generate(self.ws, self.cfg, cancel=cancel, model="gpt")
        path = Path(result["path"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.parent, self.vault / "論文筆記")
        self.assertEqual({k: result[k] for k in ("figures", "diagrams", "skipped")},
                         {"figures": 1, "diagrams": 1, "skipped": 0})
        text = unquote(path.read_text())
        self.assertTrue(text.startswith("---\n"))
        self.assertEqual(text.count("\n# "), 1)
        self.assertIn("> Evidence\n> （第 1 頁）", text)
        self.assertLess(text.index("](附圖/"), text.index("## 結果"))
        self.assertLess(text.index("> Evidence"), text.index("## 結果"))
        self.assertNotIn("{{", text)
        self.assertNotIn("## 其他劃線", text)
        self.assertNotIn("## 重要圖表", text)
        image = next((path.parent / "附圖").iterdir())
        self.assertIn(f"](附圖/{image.name})", text)
        self.assertTrue(image.read_bytes().startswith(b"\x89PNG"))
        args, kwargs = self.run.call_args
        self.assertEqual(args[0]["engine"], "codex")
        self.assertEqual(args[2], self.ws.root)
        self.assertIn("Paper evidence", args[1])
        self.assertIs(kwargs["cancel"], cancel)

    def test_generate_twice_creates_second_file_and_keeps_first(self):
        with patch("easyread.obsidian_vault.stamp", return_value="20261022-123456"):
            first = Path(obsidian_note.generate(self.ws, self.cfg)["path"])
            before = first.read_bytes()
            self.data["hook"] = "第二份"
            second = Path(obsidian_note.generate(self.ws, self.cfg)["path"])
            third = Path(obsidian_note.generate(self.ws, self.cfg)["path"])
        self.assertEqual(second.name, "TEST-20261022-123456.md")
        self.assertEqual(third.name, "TEST-20261022-123456-2.md")
        self.assertEqual(first.read_bytes(), before)
        self.assertNotEqual(second.read_bytes(), before)

    def test_generate_bad_json_writes_nothing(self):
        (self.vault / "keep.md").write_bytes(b"keep")
        before = self.snapshot()
        self.run.side_effect = None
        self.run.return_value = "not JSON"
        with self.assertRaises(ValueError):
            obsidian_note.generate(self.ws, self.cfg)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.vault / "論文筆記").exists())

    def test_generate_engine_error_writes_nothing(self):
        before = self.snapshot()
        self.run.side_effect = engines.EngineError("fake engine failure")
        with self.assertRaisesRegex(engines.EngineError, "fake engine failure"):
            obsidian_note.generate(self.ws, self.cfg)
        self.assertEqual(self.snapshot(), before)

    def test_generate_unset_vault_raises(self):
        self.cfg["obsidian_vault"] = ""
        with self.assertRaises(ValueError) as error:
            obsidian_note.generate(self.ws, self.cfg)
        self.assertEqual(str(error.exception), tr("尚未设置 Obsidian 文件夹"))
        self.run.assert_not_called()
        self.assertEqual(self.snapshot(), {})

    def test_generate_skips_figure_without_box_but_succeeds(self):
        self.paper["blocks"][1].pop("box")
        write_json_atomic(self.ws.paper_path, self.paper)
        result = obsidian_note.generate(self.ws, self.cfg)
        self.assertEqual((result["figures"], result["skipped"]), (0, 1))
        self.assertNotIn("![", Path(result["path"]).read_text())

    def test_generate_does_not_touch_other_vault_files(self):
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b'{"keep":true}')
        (self.vault / "existing.md").write_bytes(b"existing note\x00")
        before = self.snapshot()
        obsidian_note.generate(self.ws, self.cfg)
        after = self.snapshot()
        for name, content in before.items():
            self.assertEqual(after[name], content)

    def test_generate_deduplicates_and_skips_failed_or_unknown_figures(self):
        self.data["figures"] *= 2
        self.data["figures"].append({"id": "unknown", "desc": "missing"})
        for error in (ValueError("crop"), OSError("write"), RuntimeError("pdfium")):
            with self.subTest(error=error), patch("easyread.obsidian_figures.export_figure", side_effect=error) as export:
                result = obsidian_note.generate(self.ws, self.cfg)
                self.assertEqual((result["figures"], result["skipped"]), (0, 2))
                export.assert_called_once()


class EndpointTest(GenerateSetup):
    def setUp(self):
        super().setUp()
        cfg_patch = patch("easyread.config.load", side_effect=lambda: copy.deepcopy(self.cfg))
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        # 禁止 App 启动无限循环，改用可停止的真实小任务线程。
        with patch("easyread.jobs.threading.Thread.start"):
            self.app = server.App(self.cfg)
        handler = type("ObsidianHandler", (server.Handler,), {"app": self.app})
        self.handler = handler
        try:
            self.httpd = launch._Server(("127.0.0.1", 0), handler)
        except PermissionError:
            # 沙箱禁止 bind 时仍走完整 HTTP 解析、do_POST 与 do_GET。
            self.httpd = None
            self.worker = None
            return
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.httpd.shutdown)
        self.worker = None

    def start_worker(self):
        original = self.app.jobs.small.get
        def get():
            job = original()
            if job is None:
                raise StopIteration
            return job
        self.app.jobs.small.get = get
        def work():
            try:
                self.app.jobs._small_loop()
            except StopIteration:
                pass
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        def stop():
            self.app.jobs.small.put(None)
            self.worker.join(3)
            self.assertFalse(self.worker.is_alive())
        self.addCleanup(stop)

    def req(self, method, path=None, body=None, token=True):
        if self.httpd is None:
            payload = json.dumps(body or {}).encode() if method == "POST" else b""
            headers = [f"{method} {path or f'/api/p/{self.ws.id}/obsidian-note'} HTTP/1.1",
                       "Host: 127.0.0.1:0", "Connection: close", f"Content-Length: {len(payload)}"]
            if token:
                headers.append("X-Token: " + self.app.token)
            request = ("\r\n".join(headers) + "\r\n\r\n").encode() + payload
            output = bytearray()
            sock = SimpleNamespace(makefile=lambda *a, **kw: io.BytesIO(request), sendall=output.extend)
            self.handler(sock, ("127.0.0.1", 1), SimpleNamespace(server_address=("127.0.0.1", 0)))
            response = http.client.HTTPResponse(SimpleNamespace(makefile=lambda *a: io.BytesIO(output)))
            response.begin()
            return response.status, json.loads(response.read())
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        try:
            headers = {"X-Token": self.app.token} if token else {}
            conn.request(method, path or f"/api/p/{self.ws.id}/obsidian-note",
                         body=json.dumps(body or {}) if method == "POST" else None, headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_endpoint_requires_token(self):
        self.assertEqual(self.req("POST", token=False)[0], 403)
        self.assertEqual(self.app.jobs.small_status(), [])
        self.run.assert_not_called()

    def test_endpoint_400_when_vault_unset(self):
        self.cfg["obsidian_vault"] = ""
        status, body = self.req("POST")
        self.assertEqual((status, body), (400, {"error": tr("尚未设置 Obsidian 文件夹")}))
        self.assertEqual(self.app.jobs.small_status(), [])
        self.run.assert_not_called()

    def test_endpoint_runs_job_to_done(self):
        def reply(*args, **kwargs):
            job = self.app.jobs.small_status(self.ws.id)[0]
            self.assertEqual((job["state"], job["message"]), ("running", tr("模型思考中")))
            return json.dumps(self.data)
        self.run.side_effect = reply
        self.start_worker()
        status, submitted = self.req("POST", body={"model": "gpt"})
        self.assertEqual(status, 200)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, body = self.req("GET", f"/api/jobs?pid={self.ws.id}")
            job = next(j for j in body["jobs"] if j["id"] == submitted["id"])
            if job["state"] in ("done", "error"):
                break
            time.sleep(.01)
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(job["message"], tr("完成"))
        self.assertTrue(Path(job["path"]).is_file())
        self.assertEqual((job["figures"], job["diagrams"], job["skipped"]), (1, 1, 0))
        self.assertEqual(self.run.call_args.args[0]["engine"], "codex")

    def test_endpoint_engine_error_marks_job_error(self):
        self.run.side_effect = engines.EngineError("fake failure")
        self.start_worker()
        self.assertEqual(self.req("POST")[0], 200)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, body = self.req("GET", f"/api/jobs?pid={self.ws.id}")
            job = body["jobs"][0]
            if job["state"] == "error":
                break
            time.sleep(.01)
        self.assertEqual((job["state"], job["message"]), ("error", "fake failure"))
        self.assertEqual(self.snapshot(), {})
