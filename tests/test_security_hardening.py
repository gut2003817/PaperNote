"""2026-10-22 資安加固：(1) 改 base_url 不能默默沿用已存 Key (2) 文獻庫不能搬到別人的目錄 (3) 寫入令牌不經 JSON 接口回傳。
    python -m pytest tests/test_security_hardening.py -q
說明見 docs/security-hardening-2026-10-22.md。
"""
import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread import cloudlib, config, key_guard, launch, openai_api, server, settings_api
from easyread import chat_models  # 要在 config 之後匯入（chat_models ↔ config 互相引用）
from easyread.cli import server_token
from easyread.engines import EngineError
from easyread.library import Library
from easyread.library_api import LibraryLocation
from easyread.store import write_json_atomic

MINI_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
WEB_JS = Path(__file__).resolve().parents[1] / "easyread" / "web" / "js"
SECRET = "sk-REALSECRET1234"


class _ConfigTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        cm = patch.object(config, "CONFIG_PATH", self.root / "config.json")  # 不碰真實 config.json
        cm.start()
        self.addCleanup(cm.stop)

    def disk(self) -> dict:
        return json.loads((self.root / "config.json").read_text(encoding="utf-8"))


# ---------------- (1) base_url 與已存 Key ----------------
class BaseUrlKeyTest(_ConfigTmp):
    def setUp(self):
        super().setUp()
        # 使用者正常流程：選 DeepSeek、親手輸入 Key
        settings_api.save_config({"engine": "openai", "openai": {"preset": "deepseek", "base_url": "https://api.deepseek.com",
                                                                  "model": "deepseek-flash", "api_key": SECRET}})

    def test_attack_change_base_url_keeping_masked_key_is_refused(self):
        before = self.disk()
        for evil in ("https://evil.example/v1", "http://api.deepseek.com.evil.example", "https://api.deepseek.com:8443"):
            with self.assertRaises(ValueError):
                settings_api.save_config({"openai": {"base_url": evil, "api_key": "••••1234"}})
            with self.assertRaises(ValueError):  # 不帶 api_key 欄位也一樣
                settings_api.save_config({"openai": {"preset": "deepseek", "base_url": evil}})
        self.assertEqual(self.disk(), before)  # 整個不寫盤

    def test_engine_never_sees_evil_url_with_saved_key(self):
        with self.assertRaises(ValueError):
            settings_api.save_config({"openai": {"base_url": "https://evil.example/v1"}})
        o = config.load()["openai"]
        self.assertEqual(o["base_url"], "https://api.deepseek.com")
        self.assertEqual(o["api_key"], SECRET)

    def test_legit_custom_url_with_retyped_key_is_saved(self):
        settings_api.save_config({"openai": {"base_url": "https://proxy.example/v1", "api_key": "sk-new"}})
        o = config.load()["openai"]
        self.assertEqual((o["base_url"], o["api_key"]), ("https://proxy.example/v1", "sk-new"))
        self.assertEqual(o["key_origins"]["deepseek"], ["https://proxy.example:443"])
        # 之後同一個地址、打碼 Key（設定頁每次存都這樣送）照常可存
        settings_api.save_config({"openai": {"base_url": "https://proxy.example/v1/", "api_key": "••••-new", "model": "m2"}})
        self.assertEqual(config.load()["openai"]["model"], "m2")

    def test_official_preset_and_same_url_still_work(self):
        settings_api.save_config({"openai": {"preset": "deepseek", "base_url": "https://api.deepseek.com", "api_key": "••••1234", "model": "x"}})
        settings_api.save_config({"openai": {"preset": "openai", "base_url": "https://api.openai.com/v1", "api_key": ""}})  # 換到別家官方地址
        self.assertEqual(config.load()["openai"]["preset"], "openai")

    def test_non_http_scheme_refused(self):
        for bad in ("file:///etc/passwd", "ftp://x.example", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                settings_api.save_config({"openai": {"base_url": bad, "api_key": "sk-typed"}})
        with self.assertRaises(EngineError):
            openai_api._base({"base_url": "file:///etc", "model": "m"})
        with self.assertRaises(EngineError):
            openai_api.models({"base_url": "file:///etc"})

    def test_key_origins_cannot_be_injected(self):
        with self.assertRaises(ValueError):
            settings_api.save_config({"openai": {"base_url": "https://evil.example", "key_origins": {"deepseek": ["https://evil.example:443"]}}})
        for bad in ({"key_origins_v": 0}, {"keys": {"deepseek": "x"}}):
            with self.assertRaises(ValueError):
                settings_api.save_config({"openai": bad})
        for bad in ({"unknown": 1}, {"port": 1}, {"engine": "evil"}, {"auto_translate": "yes"}, {"chat": "x"}, {"chat": {"other": 1}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings_api.save_config(bad)

    EVIL_CARD = {"id": "evil", "engine": "openai", "preset": "deepseek", "base_url": "https://evil.example/v1", "model": "x", "name": "x"}

    def test_repro_chat_in_config_patch_refused(self):
        # 審查重現：/api/config 的 patch 帶 chat，加一張 evil 地址、沿用 DeepSeek 已存 Key 的卡片
        before = self.disk()
        with self.assertRaises(ValueError):
            settings_api.save_config({"chat": {"models": [self.EVIL_CARD]}})
        self.assertEqual(self.disk(), before)
        with self.assertRaises(ValueError):  # 接著把翻譯的 base_url 改成 evil 也不行
            settings_api.save_config({"openai": {"base_url": "https://evil.example/v1"}})
        self.assertEqual(self.disk(), before)

    def test_repro_preplant_card_then_user_enters_key(self):
        # 對方先替「還沒存 Key」的服務商埋一張 evil 卡片（沒 Key 可偷，存得進去）
        settings_api.save_chat_models({"models": [{**self.EVIL_CARD, "preset": "zhipu"}], "keys": {}})
        # 之後使用者在翻譯設定（官方地址）輸入智譜的 Key
        settings_api.save_config({"openai": {"preset": "zhipu", "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "sk-zhipu-REAL"}})
        cfg = config.load()
        self.assertEqual(cfg["openai"]["key_origins"]["zhipu"], [])
        with self.assertRaises(EngineError):  # 用的時候擋：evil 卡片拿不到 Key
            chat_models.engine_cfg(cfg, "evil")
        o = {**cfg["openai"], "preset": "zhipu", "base_url": "https://evil.example/v1", "api_key": "sk-zhipu-REAL"}
        with self.assertRaises(EngineError):
            openai_api._headers(o)
        # 使用者在名單裡另一張卡片（自己的代理）輸入同一把 Key：只授權那張卡片的地址，evil 仍然不行
        mine = {"id": "mine", "engine": "openai", "preset": "zhipu", "base_url": "https://proxy.mine.example/v1", "model": "y", "name": "y"}
        settings_api.save_chat_models({"models": [{**self.EVIL_CARD, "preset": "zhipu"}, mine], "keys": {"zhipu": "sk-zhipu-REAL"},
                                       "key_urls": {"zhipu": mine["base_url"]}})
        cfg = config.load()
        self.assertEqual(chat_models.engine_cfg(cfg, "mine")[0]["openai"]["api_key"], "sk-zhipu-REAL")
        with self.assertRaises(EngineError):
            chat_models.engine_cfg(cfg, "evil")

    def test_use_time_refuses_unauthorized_saved_key(self):
        # 繞過存檔檢查、直接寫進磁碟的設定（已遷移過）：送出時仍擋
        cfg = self.disk()
        cfg["openai"]["base_url"] = "https://evil.example/v1"
        cfg["chat"] = {"models": [self.EVIL_CARD], "default": "evil"}
        write_json_atomic(config.CONFIG_PATH, cfg)
        loaded = config.load()
        self.assertNotIn("https://evil.example:443", loaded["openai"]["key_origins"].get("deepseek", []))  # 遷移只做一次，不從磁碟推導
        with self.assertRaises(EngineError):
            openai_api._headers(loaded["openai"])
        with self.assertRaises(EngineError):
            chat_models.engine_cfg(loaded, "evil")
        # 官方地址照常帶 Key；剛輸入的 Key（_typed_key）不受限
        self.assertIn("Authorization", openai_api._headers({**loaded["openai"], "base_url": "https://api.deepseek.com"}))
        self.assertIn("Authorization", openai_api._headers({"base_url": "https://any.example", "api_key": "k", "_typed_key": True}))

    def test_attacker_own_key_authorization_revoked_by_new_key(self):
        settings_api.save_config({"openai": {"base_url": "https://evil.example/v1", "api_key": "sk-attacker"}})
        settings_api.save_config({"openai": {"base_url": "https://api.deepseek.com", "api_key": "sk-user-new"}})
        self.assertFalse(key_guard.may_send(config.load(), "deepseek", "https://evil.example/v1"))

    def test_same_key_resent_adds_url(self):
        # 設定頁先存名單（Key 在卡片 U 輸入），再存翻譯設定（同一把 Key、翻譯用 T）：兩個地址都要能用
        u, t = "https://u.example/v1", "https://t.example/v1"
        settings_api.save_chat_models({"models": [{**self.EVIL_CARD, "id": "u", "base_url": u}], "keys": {"deepseek": "sk-k2"}, "key_urls": {"deepseek": u}})
        settings_api.save_config({"openai": {"base_url": t, "api_key": "sk-k2"}})
        cfg = config.load()
        self.assertTrue(key_guard.may_send(cfg, "deepseek", u) and key_guard.may_send(cfg, "deepseek", t))

    def test_legacy_migration_once_without_rewriting_on_load(self):
        write_json_atomic(config.CONFIG_PATH, {"openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": SECRET, "keys": {"": SECRET}},
                                               "chat": {"models": [{"id": "c", "engine": "openai", "preset": "", "base_url": "http://10.0.0.2/v1", "model": "m"},
                                                                   {"id": "z", "engine": "openai", "preset": "zhipu", "base_url": "https://z.example", "model": "m"}]}})
        raw = config.CONFIG_PATH.read_bytes()
        o = config.load()["openai"]
        self.assertEqual(config.CONFIG_PATH.read_bytes(), raw)  # 讀取不改寫檔案
        self.assertEqual(sorted(o["key_origins"][""]), ["http://10.0.0.2:80", "http://192.168.1.5:8000"])
        self.assertNotIn("zhipu", o["key_origins"])  # 當時沒 Key 的服務商不遷移
        settings_api.save_config({"batch_pages": 3})
        self.assertEqual(self.disk()["openai"]["key_origins_v"], 1)

    def test_legacy_custom_config_keeps_working(self):
        # 升級前的設定：自訂地址 + Key，沒有 key_origins
        write_json_atomic(config.CONFIG_PATH, {"engine": "openai", "openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": SECRET,
                                                                               "keys": {"": SECRET}, "model": "local"}})
        settings_api.save_config({"openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": "••••1234", "model": "local"}})
        settings_api.save_config({"openai": {"preset": "deepseek", "base_url": "https://api.deepseek.com", "api_key": "••••"}})  # 切走
        settings_api.save_config({"openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": "••••1234"}})  # 再切回：不用重填
        with self.assertRaises(ValueError):
            settings_api.save_config({"openai": {"preset": "", "base_url": "https://evil.example/v1", "api_key": "••••1234"}})

    # 「問 AI」名單：自訂地址卡片
    def test_chat_card_with_evil_url_refused_without_key(self):
        before = self.disk()
        card = {"engine": "openai", "preset": "deepseek", "base_url": "https://evil.example/v1", "model": "x", "name": "x"}
        with self.assertRaises(ValueError):
            settings_api.save_chat_models({"models": [card], "keys": {"deepseek": "••••1234"}})
        self.assertEqual(self.disk(), before)
        # 使用者自己在同一次儲存裡重新輸入 Key：可以
        settings_api.save_chat_models({"models": [card], "keys": {"deepseek": "sk-typed-again"}, "key_urls": {"deepseek": card["base_url"]}})
        self.assertIn("https://evil.example:443", config.load()["openai"]["key_origins"]["deepseek"])
        # 已存的卡片不動、再存一次（打碼 Key）：可以
        settings_api.save_chat_models({"models": [card], "keys": {}})

    def test_chat_card_without_custom_url_unaffected(self):
        settings_api.save_chat_models({"models": [{"engine": "openai", "preset": "deepseek", "model": "x"},
                                                  {"engine": "claude", "model": "opus"}]})
        self.assertEqual(len(config.load()["chat"]["models"]), 2)

    def test_list_models_never_sends_saved_key_to_new_url(self):
        with patch.object(openai_api, "models", return_value=["m"]) as m:
            r = settings_api.list_models({"base_url": "https://evil.example/v1", "preset": "deepseek", "api_key": "••••1234"})
            self.assertFalse(r["ok"])
            m.assert_not_called()
            r = settings_api.list_models({"base_url": "file:///etc", "preset": "deepseek", "api_key": "sk-typed"})
            self.assertFalse(r["ok"])
            m.assert_not_called()
            # 正常：官方地址用已存 Key；新地址用剛輸入的 Key
            self.assertTrue(settings_api.list_models({"base_url": "https://api.deepseek.com", "preset": "deepseek", "api_key": "••••1234"})["ok"])
            self.assertEqual(m.call_args[0][0]["api_key"], SECRET)
            self.assertTrue(settings_api.list_models({"base_url": "https://evil.example/v1", "preset": "deepseek", "api_key": "sk-typed"})["ok"])
            self.assertEqual(m.call_args[0][0]["api_key"], "sk-typed")

    def test_origin_normalization(self):
        self.assertEqual(key_guard.origin("HTTPS://API.Example.com/v1/"), "https://api.example.com:443")
        self.assertEqual(key_guard.origin("http://127.0.0.1:11434/v1"), "http://127.0.0.1:11434")
        self.assertEqual(key_guard.origin("https://a.example@evil.example/"), "https://evil.example:443")
        self.assertEqual(key_guard.origin("file:///x"), "")
        self.assertEqual(key_guard.origin("http://x:bad/"), "")


# ---------------- (2) 文獻庫搬家目標必須屬於目前使用者 ----------------
@unittest.skipUnless(hasattr(os, "getuid"), "POSIX only")
class LibraryMoveOwnerTest(_ConfigTmp):
    def setUp(self):
        super().setUp()
        self.src, self.dst = self.root / "source", self.root / "EasyRead"
        self.src.mkdir()
        for k in ("EASYREAD_LIBRARY", "COREAD_LIBRARY"):
            cm = patch.dict(os.environ, {})
            cm.start()
            self.addCleanup(cm.stop)
            os.environ.pop(k, None)
        cm = patch("easyread.cloudlib.detect", return_value=[])
        cm.start()
        self.addCleanup(cm.stop)
        config.save({"library_dir": str(self.src)})
        folder = self.src / "p1"
        folder.mkdir()
        write_json_atomic(folder / "item.json", {})
        write_json_atomic(folder / "paper.json", {"meta": {}})
        (folder / "source.pdf").write_bytes(b"%PDF p1")
        self.location = LibraryLocation(SimpleNamespace(lib=Library(self.src), jobs=SimpleNamespace(busy=lambda: False), presence=None))

    def test_move_into_other_users_folder_refused(self):
        with patch.object(cloudlib.os, "getuid", return_value=os.getuid() + 4242):  # 模擬目錄屬於別的帳號
            with self.assertRaisesRegex(ValueError, "不属于当前用户|does not belong|不屬於"):
                self.location.move({"path": str(self.dst), "mode": "copy"})
        self.assertFalse(self.dst.exists())
        self.assertEqual(config.load()["library_dir"], str(self.src))
        self.assertEqual(self.location.status, "idle")

    def test_move_into_root_owned_shared_tmp_refused(self):
        shared = Path("/tmp").resolve()
        if shared.stat().st_uid == os.getuid():
            self.skipTest("/tmp 屬於目前使用者")
        target = shared / ("easyread-attack-" + os.urandom(4).hex())
        with self.assertRaises(ValueError):
            self.location.move({"path": str(target), "mode": "copy"})
        self.assertFalse(target.exists())
        self.assertEqual(config.load()["library_dir"], str(self.src))

    def test_move_into_group_or_world_writable_folder_refused(self):
        for bits in (0o770, 0o707, 0o777):
            target = self.root / f"shared-{bits:o}"
            target.mkdir()
            os.chmod(target, bits)
            with self.subTest(mode=oct(bits)), self.assertRaisesRegex(ValueError, "其他用户也能写入|Other users|其他使用者"):
                self.location.move({"path": str(target), "mode": "copy"})
        self.assertEqual(config.load()["library_dir"], str(self.src))

    def test_use_library_with_foreign_owned_file_refused(self):
        lib = self.root / "other" / "EasyRead"
        (lib / "p2").mkdir(parents=True)
        write_json_atomic(lib / "p2" / "item.json", {})
        write_json_atomic(lib / "p2" / "paper.json", {"meta": {}})
        planted = lib / "p2" / "source.pdf"
        planted.write_bytes(b"%PDF evil")
        real = Path.lstat

        def fake(self_, *a, **k):
            st = real(self_, *a, **k)
            if self_ == planted:
                return SimpleNamespace(st_uid=os.getuid() + 4242, st_mode=st.st_mode)
            return st
        with patch.object(Path, "lstat", fake):
            with self.assertRaisesRegex(ValueError, "不属于当前用户|not owned|不屬於"):
                self.location.move({"path": str(lib), "mode": "use"})
        self.assertEqual(config.load()["library_dir"], str(self.src))
        self.assertTrue(self.location.move({"path": str(lib), "mode": "use"})["ok"])  # 全是自己的檔案：照常可用

    def test_move_into_own_folder_still_works(self):
        r = self.location.move({"path": str(self.dst), "mode": "copy"})
        self.assertTrue(r["ok"])
        self.assertTrue((self.dst / "p1" / "source.pdf").is_file())


# ---------------- (3) 寫入令牌只在頁面 HTML ----------------
class TokenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": cls.tmp.name})
        cls.env.start()
        cls.cfg = patch.object(server.config, "CONFIG_PATH", Path(cls.tmp.name) / "no-config.json")
        cls.cfg.start()
        cls.app = server.App(server.config.load())
        server.Handler.app = cls.app
        cls.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        ws, _ = cls.app.lib.create_from_pdf(MINI_PDF, "x.pdf", {"title_en": "T"})
        cls.pid = ws.id
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.cfg.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.url + path, timeout=5).read().decode("utf-8")

    def post(self, path, token=None, body=b"{}"):
        h = {"Content-Type": "application/json"}
        if token is not None:
            h["X-Token"] = token
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + path, data=body, headers=h), timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_json_apis_no_longer_return_token(self):
        for path in ("/api/library", f"/api/p/{self.pid}/state", "/api/config", "/api/jobs"):
            body = self.get(path)
            self.assertNotIn(self.app.token, body, path)
            self.assertNotIn('"token"', body, path)

    def test_pages_carry_token_in_meta(self):
        for path in ("/", f"/read/{self.pid}"):
            self.assertIn(f'<meta name="easyread-token" content="{self.app.token}">', self.get(path))

    def test_write_requires_token_and_page_token_works(self):
        self.assertEqual(self.post("/api/prefs"), 403)
        self.assertEqual(self.post("/api/prefs", "wrong"), 403)
        self.assertEqual(self.post("/api/prefs", self.app.token[:-1]), 403)
        token = server_token(self.url)  # CLI / Electron 的做法：從首頁 HTML 取
        self.assertEqual(token, self.app.token)
        self.assertEqual(self.post("/api/prefs", token), 200)

    def test_bad_token_closes_connection_so_body_is_not_reparsed(self):
        # 前端拿到 403 會重取令牌再送；舊行為是不讀請求體就回 403、連線保持，殘留的請求體被當成下一個請求（501）
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        c.request("POST", "/api/prefs", body=b'{"reader":{"x":1}}', headers={"X-Token": "stale", "Content-Type": "application/json"})
        r = c.getresponse()
        self.assertEqual((r.status, json.loads(r.read())["error"]), (403, "bad token"))
        c.request("POST", "/api/prefs", body=b'{"reader":{"x":2}}', headers={"X-Token": self.app.token, "Content-Type": "application/json"})
        self.assertEqual(c.getresponse().status, 200)
        c.close()

    def test_http_config_patch_with_chat_refused(self):
        # 走真正的 HTTP /api/config：patch 帶 chat，加一張 evil 地址、沿用已存 Key 的卡片
        def post_json(path, obj):
            req = urllib.request.Request(self.url + path, data=json.dumps(obj).encode(),
                                         headers={"Content-Type": "application/json", "X-Token": self.app.token})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        status, _ = post_json("/api/config", {"openai": {"preset": "deepseek", "base_url": "https://api.deepseek.com", "api_key": SECRET}})
        self.assertEqual(status, 200)
        card = {"id": "evil", "engine": "openai", "preset": "deepseek", "base_url": "https://evil.example/v1", "model": "x"}
        status, body = post_json("/api/config", {"chat": {"models": [card], "default": "evil"}})
        self.assertEqual(status, 400, body)
        self.assertNotIn("evil", json.dumps(config.load()["chat"]))
        status, body = post_json("/api/config", {"openai": {"base_url": "https://evil.example/v1"}})
        self.assertEqual(status, 400, body)
        self.assertEqual(config.load()["openai"]["base_url"], "https://api.deepseek.com")

    def test_frontend_no_longer_reads_token_from_json(self):
        bad = re.compile(r"\.token\s*=\s*(d|data|info|res|r)\.token|\)\)\.token|\.json\(\)\)\.token")
        hits = [f"{p}:{i}" for p in WEB_JS.rglob("*.js") for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if bad.search(line)]
        self.assertEqual(hits, [])
        main = (WEB_JS.parents[2] / "electron" / "main.cjs").read_text(encoding="utf-8")
        self.assertNotIn("info.token", main)


if __name__ == "__main__":
    unittest.main()
