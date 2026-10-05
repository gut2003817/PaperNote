"""笔记图片：上传校验（魔术字节、大小、token）、读取白名单、内容定址去重、zip 导出、离线 HTML 内嵌、搬库和回收站。"""
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from easyread import build, cloudlib, config, launch, note_images, server, trash
from easyread.library import Library
from easyread.library_api import LibraryLocation
from easyread.store import Workspace, write_json_atomic


def make_png(color=(200, 30, 30), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def make_fmt(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), (1, 2, 3)).save(buf, fmt)
    return buf.getvalue()


PID = "paper0000001"


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cm = patch.dict(os.environ, {"EASYREAD_LIBRARY": str(Path(self.tmp.name) / "lib"), "EASYREAD_HOME": self.tmp.name})
        cm.start(); self.addCleanup(cm.stop)
        self.app = server.App(config.load())
        server.Handler.app = self.app
        self.root = self.app.lib.root / PID
        self.root.mkdir(parents=True)
        write_json_atomic(self.root / "paper.json", {"meta": {"title_en": "T"}, "blocks": []})
        write_json_atomic(self.root / "item.json", {})
        self.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def req(self, method, path, body=None, headers=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if token:
            h["X-Token"] = self.app.token
        try:
            c.request(method, path, body=body, headers=h)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def upload(self, data, **kw):
        return self.req("POST", f"/api/p/{PID}/note-image", data, kw.pop("headers", {"Content-Type": "application/octet-stream"}), **kw)

    def files(self):
        d = self.root / "note-images"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []


class UploadTest(ServerCase):
    def test_png_roundtrip_bytes_equal_and_headers(self):
        data = make_png()
        st, _, body = self.upload(data)
        self.assertEqual(st, 200, body)
        res = json.loads(body)
        self.assertRegex(res["name"], r"^[0-9a-f]{32}\.png$")
        self.assertEqual(res["md"], f"![](note-images/{res['name']})")
        st, h, got = self.req("GET", f"/p/{PID}/note-images/{res['name']}", token=False)
        self.assertEqual(st, 200)
        self.assertEqual(got, data)
        self.assertEqual(h["Content-Type"], "image/png")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_all_four_formats_accepted_with_server_chosen_extension(self):
        for fmt, ext in (("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp"), ("GIF", "gif")):
            st, _, body = self.upload(make_fmt(fmt), headers={"Content-Type": "text/plain"})  # 客户端说什么都无所谓
            self.assertEqual(st, 200, (fmt, body))
            self.assertTrue(json.loads(body)["name"].endswith("." + ext))

    def test_svg_with_script_rejected(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        st, _, body = self.upload(svg, headers={"Content-Type": "image/svg+xml"})
        self.assertEqual(st, 400, body)
        self.assertEqual(self.files(), [])

    def test_html_claiming_png_rejected(self):
        st, _, _ = self.upload(b"<html><script>alert(1)</script></html>", headers={"Content-Type": "image/png", "X-Filename": "a.png"})
        self.assertEqual(st, 400)
        self.assertEqual(self.files(), [])

    def test_fake_extension_and_truncated_or_mismatched_content_rejected(self):
        st, _, _ = self.req("POST", f"/api/p/{PID}/note-image?name=evil.png", b"MZ\x90\x00 not an image", {"Content-Type": "image/png"})
        self.assertEqual(st, 400)
        png = make_png()
        st, _, _ = self.upload(png[:20])  # 文件头对、内容残缺
        self.assertEqual(st, 400)
        st, _, _ = self.upload(b"GIF89a" + b"\x00" * 10)  # 只有文件头
        self.assertEqual(st, 400)
        st, _, _ = self.upload(b"")
        self.assertEqual(st, 400)
        self.assertEqual(self.files(), [])

    def test_over_10mb_rejected_413_without_storing(self):
        big = make_png() + b"\x00" * (note_images.MAX_BYTES + 1)
        st, _, body = self.upload(big)
        self.assertEqual(st, 413, body)
        self.assertIn("MB", json.loads(body)["error"])
        self.assertEqual(self.files(), [])
        # 服务还活着、连接没被残留数据弄坏
        self.assertEqual(self.upload(make_png())[0], 200)

    def test_exactly_at_limit_checked_by_validate(self):
        with self.assertRaises(ValueError):
            note_images.validate(make_png() + b"\x00" * note_images.MAX_BYTES)

    def test_no_token_or_wrong_token_403(self):
        st, _, _ = self.upload(make_png(), token=False)
        self.assertEqual(st, 403)
        st, _, _ = self.upload(make_png(), token=False, headers={"X-Token": "nope"})
        self.assertEqual(st, 403)
        self.assertEqual(self.files(), [])

    def test_unknown_paper_404(self):
        st, _, _ = self.req("POST", "/api/p/nopaper0001/note-image", make_png())
        self.assertEqual(st, 404)

    def test_same_image_twice_stores_one_file(self):
        data = make_png((5, 6, 7))
        a = json.loads(self.upload(data)[2])["name"]
        b = json.loads(self.upload(data)[2])["name"]
        self.assertEqual(a, b)
        self.assertEqual(self.files(), [a])
        self.assertFalse([n for n in self.files() if n.endswith(".tmp")])


class ReadWhitelistTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.name = json.loads(self.upload(make_png())[2])["name"]
        (self.root / "secret.txt").write_text("secret")

    def test_traversal_and_bad_names_all_404(self):
        n = self.name
        bad = [
            "..%2fpaper.json", "../paper.json", "..%5cpaper.json", "..\\paper.json", "%2e%2e/paper.json", "%2e%2e%2fpaper.json",
            "..%252fpaper.json", f"{n}/../paper.json", f"../note-images/{n}", f"%2e%2e%2fnote-images%2f{n}",
            n.upper(), n[:-4] + ".PNG", n[:-4] + ".svg", n[:-4] + ".png.html", n[:-4] + ".png%00.html", n[:-4] + ".png%0a",
            n + "/", "x" * 32 + ".png", n[:31] + ".png", "0" * 33 + ".png", "", ".", "..", "%2e", f"{n}%20", f"%20{n}",
            n[:-4] + ".jpeg", n[:-4] + ".bmp", "secret.txt", "..%2fsecret.txt", ("g" * 32) + ".png",
        ]
        for name in bad:
            st, _, _ = self.req("GET", f"/p/{PID}/note-images/{name}", token=False)
            self.assertEqual(st, 404, name)
        st, _, _ = self.req("GET", f"/p/{PID}/note-images/{n}", token=False)
        self.assertEqual(st, 200)

    def test_symlink_inside_folder_rejected(self):
        link = self.root / "note-images" / ("a" * 32 + ".png")
        try:
            link.symlink_to(self.root / "secret.txt")
        except OSError:
            self.skipTest("symlink not permitted")
        self.assertEqual(self.req("GET", f"/p/{PID}/note-images/{link.name}", token=False)[0], 404)

    def test_symlinked_folder_rejected(self):
        import shutil
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        shutil.copy(self.root / "note-images" / self.name, outside / self.name)
        shutil.rmtree(self.root / "note-images")
        try:
            (self.root / "note-images").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink not permitted")
        self.assertEqual(self.req("GET", f"/p/{PID}/note-images/{self.name}", token=False)[0], 404)
        self.assertEqual(self.upload(make_png((9, 9, 9)))[0], 400)

    def test_other_paper_cannot_read_this_papers_image(self):
        other = self.app.lib.root / "paper0000002"
        other.mkdir()
        write_json_atomic(other / "paper.json", {"blocks": []})
        self.assertEqual(self.req("GET", f"/p/paper0000002/note-images/{self.name}", token=False)[0], 404)


class ExportTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.name = json.loads(self.upload(make_png())[2])["name"]

    def zip_req(self, md):
        return self.req("POST", f"/api/p/{PID}/notes-zip", json.dumps({"md": md, "stem": "笔记/测试"}).encode(), {"Content-Type": "application/json"})

    def test_zip_has_notes_and_referenced_images_only(self):
        other = json.loads(self.upload(make_png((9, 9, 9)))[2])["name"]
        md = f"# T\n\n- 图：![shot](note-images/{self.name})\n- 外链 ![](http://evil/x.png)\n"
        st, h, body = self.zip_req(md)
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(body))
        self.assertEqual(sorted(z.namelist()), sorted(["notes.md", f"note-images/{self.name}"]))
        self.assertNotIn(other, "".join(z.namelist()))
        self.assertEqual(z.read(f"note-images/{self.name}"), (self.root / "note-images" / self.name).read_bytes())
        self.assertIn(f"](note-images/{self.name})", z.read("notes.md").decode())
        self.assertIsNone(z.testzip())

    def test_missing_image_does_not_leave_broken_link(self):
        ghost = "f" * 32 + ".png"
        _, _, body = self.zip_req(f"![](note-images/{ghost})")
        z = zipfile.ZipFile(io.BytesIO(body))
        self.assertEqual(z.namelist(), ["notes.md"])
        self.assertNotIn(ghost, z.read("notes.md").decode())

    def test_zip_requires_token(self):
        st, _, _ = self.req("POST", f"/api/p/{PID}/notes-zip", b"{}", token=False)
        self.assertEqual(st, 403)

    def test_offline_html_embeds_note_images(self):
        ws = Workspace(self.root)
        write_json_atomic(ws.reader_path, {"notes": {"n1": {"id": "n1", "kind": "note", "body": f"![](note-images/{self.name})"}},
                                           "paper_note": {"body": ""}})
        ghost = "e" * 32 + ".png"
        write_json_atomic(ws.discussion_path, {"entries": [{"id": "d1", "body": f"![](note-images/{ghost})"}]})
        out = build.build(ws, Path(self.tmp.name) / "o.html")
        html = out.read_text(encoding="utf-8")
        payload = json.loads(html.split('<script id="pr-data" type="application/json">')[1].split("</script>")[0].replace("\\u003c", "<"))
        uri = payload["images"][f"note-images/{self.name}"]
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertNotIn(f"note-images/{ghost}", payload["images"])  # 不存在的不收

    def test_demo_assets_mode_copies_note_images(self):
        ws = Workspace(self.root)
        write_json_atomic(ws.reader_path, {"notes": {"n1": {"id": "n1", "kind": "note", "body": f"![](note-images/{self.name})"}}})
        from easyread.site import build_demo
        out_dir = Path(self.tmp.name) / "demo"
        build_demo(ws, out_dir)
        self.assertEqual((out_dir / "assets" / f"note-images-{self.name}").read_bytes(), (self.root / "note-images" / self.name).read_bytes())
        self.assertIn(f'"note-images/{self.name}": "assets/note-images-{self.name}"', (out_dir / "index.html").read_text(encoding="utf-8"))


class LibraryMoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.src, self.dst = self.root / "source", self.root / "EasyRead"
        self.src.mkdir()
        for k, v in (("CONFIG_PATH", self.root / "config.json"),):
            cm = patch.object(config, k, v); cm.start(); self.addCleanup(cm.stop)
        cm = patch.dict(os.environ, {}); cm.start(); self.addCleanup(cm.stop)
        cm = patch("easyread.cloudlib.detect", return_value=[]); cm.start(); self.addCleanup(cm.stop)
        for name in ("EASYREAD_LIBRARY", "COREAD_LIBRARY", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            os.environ.pop(name, None)
        config.save({"library_dir": str(self.src)})
        self.lib = Library(self.src)
        self.app = SimpleNamespace(lib=self.lib, jobs=SimpleNamespace(busy=lambda: False), presence=None)

    def paper(self, pid):
        folder = self.src / pid
        folder.mkdir()
        write_json_atomic(folder / "item.json", {})
        write_json_atomic(folder / "paper.json", {"meta": {}})
        (folder / "source.pdf").write_bytes(b"%PDF " + pid.encode())
        return folder

    def test_copy_migration_carries_note_images(self):
        folder = self.paper("paper001")
        name = note_images.save(folder, make_png())
        result = LibraryLocation(self.app).move({"path": str(self.dst), "mode": "copy"})
        self.assertEqual(result["copied"], 1)
        self.assertEqual((self.dst / "paper001" / "note-images" / name).read_bytes(), make_png())

    def test_manifest_lists_note_images(self):
        folder = self.paper("paper001")
        name = note_images.save(folder, make_png())
        self.assertIn(f"note-images/{name}", cloudlib._manifest(folder))

    def test_trash_and_restore_keep_note_images(self):
        folder = self.paper("aaaaaaaaaaaa")
        name = note_images.save(folder, make_png())
        dest = self.lib.trash("aaaaaaaaaaaa")
        self.assertTrue((dest / "note-images" / name).is_file())
        self.assertIsNone(self.lib.ws("aaaaaaaaaaaa"))
        pid = trash.restore(self.src, dest.name)
        self.assertEqual((self.src / pid / "note-images" / name).read_bytes(), make_png())


if __name__ == "__main__":
    unittest.main()
