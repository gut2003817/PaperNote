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

from easyread import key_guard
from easyread.app import config
from easyread.app.cli import server_token
from easyread.chat import chat_models
from easyread.engines import openai_api
from easyread.engines.engines import EngineError
from easyread.library import cloudlib
from easyread.library.library import Library
from easyread.library.store import write_json_atomic
from easyread.server import launch, server, settings_api
from easyread.server.library_api import LibraryLocation

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
        # 自訂地址的 Key 按上游 api_keys 分槽（url:<地址>），不進 key_origins；舊的無名 Key 歸給當時的地址
        self.assertEqual(o["keys"].get("url:http://192.168.1.5:8000/v1"), SECRET)
        self.assertNotIn("", o["keys"])
        self.assertNotIn("", o["key_origins"])
        self.assertNotIn("zhipu", o["key_origins"])  # 當時沒 Key 的服務商不遷移
        # 有 Key 的服務商、自訂代理地址：遷移進 key_origins
        write_json_atomic(config.CONFIG_PATH, {"openai": {"preset": "deepseek", "base_url": "https://proxy.example/v1", "api_key": SECRET}})
        self.assertEqual(config.load()["openai"]["key_origins"]["deepseek"], ["https://proxy.example:443"])
        settings_api.save_config({"batch_pages": 3})
        self.assertEqual(self.disk()["openai"]["key_origins_v"], 1)

    def test_legacy_custom_config_keeps_working(self):
        # 升級前的設定：自訂地址 + Key，沒有 key_origins
        write_json_atomic(config.CONFIG_PATH, {"engine": "openai", "openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": SECRET,
                                                                               "keys": {"": SECRET}, "model": "local"}})
        settings_api.save_config({"openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": "••••1234", "model": "local"}})
        settings_api.save_config({"openai": {"preset": "deepseek", "base_url": "https://api.deepseek.com", "api_key": "••••"}})  # 切走
        settings_api.save_config({"openai": {"preset": "", "base_url": "http://192.168.1.5:8000/v1", "api_key": "••••1234"}})  # 再切回：不用重填
        # 改成 evil：上游把自訂地址的 Key 按地址分槽，新地址的槽是空的 → 存得進去但不帶 Key
        settings_api.save_config({"openai": {"preset": "", "base_url": "https://evil.example/v1", "api_key": "••••1234"}})
        self.assertEqual(config.load()["openai"]["api_key"], "")
        self.assertEqual(chat_models.engine_cfg({**config.load(), "chat": {"models": [
            {"id": "e", "engine": "openai", "preset": "", "base_url": "https://evil.example/v1", "model": "m"}]}}, "e")[0]["openai"]["api_key"], "")

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

    def test_use_library_with_writable_subfolder_refused(self):
        # 子目錄屬於自己、但他人可寫：別人之後仍能放檔案進來
        lib = self.root / "other2" / "EasyRead"
        (lib / "p3").mkdir(parents=True)
        write_json_atomic(lib / "p3" / "item.json", {})
        write_json_atomic(lib / "p3" / "paper.json", {"meta": {}})
        (lib / "p3" / "source.pdf").write_bytes(b"%PDF p3")
        for target, bits in ((lib / "p3", 0o777), (lib / "p3", 0o775), (lib / "p3" / "source.pdf", 0o666)):
            os.chmod(target, bits)
            with self.subTest(target=target.name, mode=oct(bits)), self.assertRaisesRegex(ValueError, "其他用户也能写入|other users can write|其他使用者也能寫入"):
                self.location.move({"path": str(lib), "mode": "use"})
            os.chmod(target, 0o755 if target.is_dir() else 0o644)
        self.assertEqual(config.load()["library_dir"], str(self.src))
        self.assertTrue(self.location.move({"path": str(lib), "mode": "use"})["ok"])

    def test_move_into_own_folder_still_works(self):
        r = self.location.move({"path": str(self.dst), "mode": "copy"})
        self.assertTrue(r["ok"])
        self.assertTrue((self.dst / "p1" / "source.pdf").is_file())


# ---------------- (4) 上游 v1.4.4 新增的本機 CLI 引擎也要過 cli_guard ----------------
NEW_CLIS = ("codebuddy", "grok", "agy", "cursor")


def frontend_settings_body(cfg: dict) -> dict:
    """照 web/js/common/settings.js 的 PR.settingsTabs.engine.collect 組出的請求（設定頁正常存檔的樣子）。"""
    c, o = cfg, cfg["openai"]
    return {"engine": c["engine"], "batch_pages": c["batch_pages"], "concurrency": c["concurrency"], "page_cap": c["page_cap"],
            "auto_translate": c["auto_translate"], "translation_instructions": c.get("translation_instructions") or "",
            "paper_concurrency": c.get("paper_concurrency") or 1,
            "claude": {"model": c["claude"]["model"], "command": c["claude"]["command"], "reasoning_effort": ""},
            "codex": {"model": c["codex"]["model"], "command": c["codex"]["command"], "reasoning_effort": "", "service_tier": ""},
            **{k: {"model": c[k].get("model") or "", "command": c[k].get("command") or "", "reasoning_effort": c[k].get("reasoning_effort") or ""} for k in NEW_CLIS},
            "openai": {"custom_apis": o.get("custom_apis") or [], "preset": o["preset"], "base_url": o["base_url"], "api": o["api"], "model": o["model"],
                       "api_key": "", "vision": o["vision"], "reasoning_effort": "", "service_tier": ""}}


class NewCliEnginesTest(_ConfigTmp):
    def test_command_repro_refused_for_every_new_engine(self):
        for name in NEW_CLIS:
            for bad in ({"command": "/bin/sh"}, {"command": "sh"}, {"command": "codebuddy --yolo"}, {"command": "./grok"},
                        {"extra_args": ["--yolo"]}, {"extra_args": ["-c", "x"]}, {"model": "--dangerous"}, {"unknown": 1}):
                with self.subTest(engine=name, patch=bad), self.assertRaises(ValueError):
                    settings_api.save_config({name: bad})
        self.assertFalse(config.CONFIG_PATH.exists())

    def test_default_names_and_empty_command_still_save(self):
        from easyread.engines import agent_cli
        from easyread import cli_guard
        for name, spec in agent_cli.SPECS.items():  # 命令名表和上游 SPECS 一致
            self.assertEqual(set(cli_guard.NAMES[name]), set(spec["commands"]), name)
        for name in NEW_CLIS:
            settings_api.save_config({name: {"command": "", "model": "some-model", "reasoning_effort": "high", "extra_args": []}})
            settings_api.save_config({name: {"command": cli_guard.NAMES[name][0]}})
        self.assertEqual(config.load()["cursor"]["command"], "agent")

    def test_spawn_time_refuses_bad_command_or_args(self):
        from easyread.engines import agent_cli, codebuddy_cli, engines
        with patch("shutil.which", return_value="/bin/sh") as which:
            for name in ("grok", "agy", "cursor"):
                self.assertIsNone(agent_cli.path(name, {"command": "/bin/sh"}))
            self.assertIsNone(codebuddy_cli.path({"command": "/bin/sh"}))
            which.assert_not_called()
        for name in NEW_CLIS:
            with self.subTest(engine=name), self.assertRaises(engines.EngineError):
                engines.guard(name, {"command": "", "extra_args": ["--yolo"]})

    def test_chat_card_for_new_cli_validates_model(self):
        for name in NEW_CLIS:
            with self.subTest(engine=name), self.assertRaises(ValueError):
                settings_api.save_chat_models({"models": [{"id": "x", "engine": name, "model": "--settings={}"}]})

    def test_frontend_shaped_settings_save_ok(self):
        settings_api.save_config(frontend_settings_body(config.load()))
        body = frontend_settings_body(config.load())
        body["batch_pages"] = 3
        self.assertEqual(settings_api.save_config(body)["config"]["batch_pages"], 3)


# ---------------- (5) 第三輪：可執行檔路徑、成批匯入來源、清理 ----------------
ALL_CLIS = {"claude": "claude", "codex": "codex", "codebuddy": "codebuddy", "grok": "grok", "agy": "agy", "cursor": "agent"}


def _exe(folder: Path, name: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_text("#!/bin/sh\necho pwned > /dev/null\n")
    os.chmod(f, 0o755)
    return str(f)


@unittest.skipUnless(hasattr(os, "getuid"), "POSIX only")
class TrustedExecutableTest(_ConfigTmp):
    def test_repro_attacker_binary_in_tmp_refused_for_all_engines(self):
        # 審查重現：<tmp>/attacker/bin/claude 檔名對、可執行 → 以前會被接受並在 /api/config/test 執行
        for engine, name in ALL_CLIS.items():
            exe = _exe(self.root / "attacker" / "bin", name)
            with self.subTest(engine=engine), self.assertRaisesRegex(ValueError, "不会执行|will not be run|不會執行"):
                settings_api.save_config({engine: {"command": exe}})
        self.assertFalse(config.CONFIG_PATH.exists())

    def test_spawn_time_rejects_untrusted_even_if_on_disk_or_in_path(self):
        from easyread.engines import agent_cli, codebuddy_cli, engines
        bindir = self.root / "evilbin"
        for name in set(ALL_CLIS.values()):
            _exe(bindir, name)
        self.assertIsNone(engines.claude_path({"command": str(bindir / "claude")}))  # 繞過存檔直接寫進設定
        with patch.dict(os.environ, {"PATH": str(bindir)}):  # PATH 被塞進暫存目錄：which 找到也不執行
            self.assertIsNone(engines.claude_path({"command": "claude"}))
            self.assertIsNone(engines.codex_path({"command": "codex"}))
            for name in ("grok", "agy", "cursor"):
                self.assertIsNone(agent_cli.path(name, {"command": ""}))
            self.assertIsNone(codebuddy_cli.path({"command": ""}))

    def test_writable_or_foreign_dirs_refused_outside_tmp_rules(self):
        from easyread import cli_guard, path_guard
        with patch.object(path_guard, "_untrusted_roots", return_value=[]):  # 只看擁有者與權限
            good = _exe(self.root / "ok" / "bin", "claude")
            self.assertEqual(cli_guard.check_command("claude", good), good)
            for bits in (0o777, 0o757):
                os.chmod(self.root / "ok" / "bin", bits)
                with self.subTest(dir_mode=oct(bits)), self.assertRaises(ValueError):
                    cli_guard.check_command("claude", good)
            os.chmod(self.root / "ok" / "bin", 0o755)
            os.chmod(good, 0o777)
            with self.assertRaises(ValueError):
                cli_guard.check_command("claude", good)
            os.chmod(good, 0o755)
            # 符號連結：自己的目錄裡放一個連到別人可寫目錄的 claude
            bad_real = _exe(self.root / "ww", "real-claude")
            os.chmod(self.root / "ww", 0o777)
            link = self.root / "ok" / "bin2" / "claude"
            link.parent.mkdir()
            link.symlink_to(bad_real)
            with self.assertRaises(ValueError):
                cli_guard.check_command("claude", str(link))
            os.chmod(self.root / "ww", 0o755)
            with patch.object(os, "getuid", return_value=os.getuid() + 4242):  # 檔案屬於別的帳號
                self.assertFalse(path_guard.trusted_path(good))

    @unittest.skipUnless(os.path.exists(os.path.expanduser("~/.local/bin/claude")), "本機沒有 ~/.local/bin/claude")
    def test_real_user_install_still_trusted(self):
        from easyread import cli_guard
        p = os.path.expanduser("~/.local/bin/claude")
        self.assertEqual(cli_guard.check_command("claude", p), p)
        self.assertTrue(cli_guard.which_trusted("claude"))


@unittest.skipUnless(hasattr(os, "getuid"), "POSIX only")
class BulkImportSourceTest(_ConfigTmp):
    def setUp(self):
        super().setUp()
        self.secret = self.root / "victim" / "tax.pdf"
        self.secret.parent.mkdir()
        self.secret.write_bytes(b"%PDF-1.4\n% secret\n%%EOF\n")

    def test_folder_in_tmp_refused(self):
        from easyread.bulk import folder
        with self.assertRaisesRegex(ValueError, "不能导入|cannot be imported|不能匯入"):
            folder.read(str(self.secret.parent))

    def test_folder_writable_or_foreign_refused_and_foreign_file_skipped(self):
        from easyread import path_guard
        from easyread.bulk import folder
        src = self.root / "mine"
        src.mkdir()
        (src / "ok.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (src / "leak.pdf").symlink_to(self.secret)  # 指到“暫存／共用目錄”裡的檔案
        with patch.object(path_guard, "_untrusted_roots", return_value=[str(self.secret.parent)]):
            snap = folder.read(str(src))
            got = {e.key: e for e in snap.entries}
            self.assertIsNotNone(got["ok.pdf"].pdf)
            self.assertNotIn("leak.pdf", got)  # 符號連結（lstat）一律不收
            os.chmod(src, 0o777)
            with self.assertRaises(ValueError):
                folder.read(str(src))
            os.chmod(src, 0o755)
            with patch.object(os, "getuid", return_value=os.getuid() + 4242):
                with self.assertRaises(ValueError):
                    folder.read(str(src))

    def test_folder_walk_skips_writable_subtrees_and_reads_with_nofollow(self):
        from easyread import path_guard
        from easyread.bulk import folder
        src = self.root / "mine3"
        (src / "good").mkdir(parents=True)
        (src / "shared").mkdir()
        (src / "good" / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (src / "shared" / "b.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        os.chmod(src / "shared", 0o777)  # 自己的子資料夾但別人可寫：別人之後能放檔案
        try:
            with patch.object(path_guard, "_untrusted_roots", return_value=[]):
                keys = {e.key for e in folder.read(str(src)).entries}
                self.assertIn(os.path.join("good", "a.pdf"), keys)
                self.assertNotIn(os.path.join("shared", "b.pdf"), keys)
        finally:
            os.chmod(src / "shared", 0o755)
        link = src / "good" / "link.pdf"
        link.symlink_to(src / "good" / "a.pdf")
        with self.assertRaises(OSError):  # O_NOFOLLOW：最後一層是符號連結就打不開
            path_guard.read_mine(link)
        self.assertTrue(path_guard.read_mine(src / "good" / "a.pdf").startswith(b"%PDF"))
        with patch.object(os, "getuid", return_value=os.getuid() + 4242), self.assertRaises(ValueError):  # 對 fd 檢查擁有者
            path_guard.read_mine(src / "good" / "a.pdf")

    def test_zotero_linked_attachment_outside_refused(self):
        import sqlite3
        from easyread import path_guard
        from easyread.zotero import reader
        from tests.zotero.fake_zotero import FakeZotero
        zdir = self.root / "Zotero"
        z = FakeZotero(zdir)
        a = z.item(title="Bait")
        att = z.item("attachment")
        z.con.execute("INSERT INTO itemAttachments VALUES (?, ?, 2, 'application/pdf', ?)", (att, a, str(self.secret)))
        z.close()
        with self.assertRaisesRegex(ValueError, "不能读取|cannot be read|不能讀取"):  # 資料夾在暫存目錄
            reader.read(str(zdir))
        with patch.object(path_guard, "_untrusted_roots", return_value=[str(self.secret.parent)]):
            e = reader.read(str(zdir)).entries[0]
            self.assertIsNone(e.pdf)  # 連結附件指到禁區：不匯入
            with patch.object(path_guard, "_untrusted_roots", return_value=[]):
                self.assertEqual(reader.read(str(zdir)).entries[0].pdf, self.secret)  # 自己的檔案照常
            os.chmod(zdir / "zotero.sqlite", 0o666)
            with self.assertRaises(ValueError):  # 別人可寫的資料庫
                reader.read(str(zdir))
        sqlite3  # noqa: B018

    def test_link_import_only_under_home(self):
        from easyread import path_guard
        from easyread.bulk.runner import Migration
        src = self.root / "mine2"
        src.mkdir()
        (src / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        imported = []
        app = SimpleNamespace(lib=SimpleNamespace(import_pdf_path=lambda *a, **k: imported.append(a) or (None, True)), jobs=None)
        with patch.object(path_guard, "_untrusted_roots", return_value=[]):
            m = Migration(app)
            m.start("folder", str(src), link=True)
            for _ in range(100):
                if m.status.get("state") != "running":
                    break
                threading.Event().wait(0.02)
        self.assertEqual(imported, [])
        self.assertIn("家目录", json.dumps(m.status, ensure_ascii=False))


@unittest.skipUnless(hasattr(os, "getuid"), "POSIX only")
class CleanupTest(_ConfigTmp):
    def _staged(self, entries):
        root = self.root / "target"
        root.mkdir()
        write_json_atomic(root / cloudlib.MIGRATION_MARKER, {"state": "copying", "entries": entries})
        return root

    def test_cleanup_refuses_foreign_or_writable_root(self):
        root = self._staged(["p1"])
        (root / "p1").mkdir()
        with patch.object(cloudlib.os, "getuid", return_value=os.getuid() + 4242):
            with self.assertRaises(ValueError):
                cloudlib.cleanup(str(root), str(self.root / "current"))
        os.chmod(root, 0o777)
        with self.assertRaises(ValueError):
            cloudlib.cleanup(str(root), str(self.root / "current"))
        os.chmod(root, 0o755)
        self.assertTrue((root / "p1").exists())
        self.assertEqual(cloudlib.cleanup(str(root), str(self.root / "current"))["removed"], 1)

    def test_cleanup_intermediate_symlink_swap_does_not_escape(self):
        outside = self.root / "outside"
        (outside / "x").mkdir(parents=True)
        (outside / "x" / "keep.txt").write_text("precious")
        root = self._staged(["sub/x"])
        (root / "sub" / "x").mkdir(parents=True)
        real_linked = cloudlib._linked

        def swap(p):  # 檢查通過之後、刪除之前，把中間的 sub 換成指向庫外的符號連結（TOCTOU）
            if Path(p).name == "x" and (root / "sub").is_dir() and not (root / "sub").is_symlink():
                import shutil
                shutil.rmtree(root / "sub")
                (root / "sub").symlink_to(outside)
            return real_linked(p)
        with patch.object(cloudlib, "_linked", side_effect=swap):
            with self.assertRaises(ValueError):
                cloudlib.cleanup(str(root), str(self.root / "current"))
        self.assertEqual((outside / "x" / "keep.txt").read_text(), "precious")


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

    def test_http_new_cli_command_repro_returns_400(self):
        for name in NEW_CLIS:
            req = urllib.request.Request(self.url + "/api/config", data=json.dumps({name: {"command": "/bin/sh", "extra_args": ["-c", "id"]}}).encode(),
                                         headers={"Content-Type": "application/json", "X-Token": self.app.token})
            with self.subTest(engine=name), self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 400)
        self.assertNotIn("/bin/sh", json.dumps(config.load()))

    def test_http_attacker_binary_and_migrate_source_return_400(self):
        def post_json(path, obj):
            req = urllib.request.Request(self.url + path, data=json.dumps(obj).encode(),
                                         headers={"Content-Type": "application/json", "X-Token": self.app.token})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        with tempfile.TemporaryDirectory() as tmp:
            exe = _exe(Path(tmp) / "attacker" / "bin", "claude")
            status, body = post_json("/api/config", {"claude": {"command": exe}})
            self.assertEqual(status, 400, body)
            (Path(tmp) / "victim").mkdir()
            (Path(tmp) / "victim" / "tax.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            for path in ("/api/migrate/scan", "/api/migrate/start"):
                status, body = post_json(path, {"source": "folder", "path": str(Path(tmp) / "victim"), "link": True})
                self.assertEqual(status, 400, (path, body))
        self.assertNotIn("attacker", json.dumps(config.load()))

    # ---- 第四輪：成批匯入只接受這次親手選的資料夾（server/pick_grants.py） ----
    def _post(self, path, obj, headers=None):
        h = {"Content-Type": "application/json", "X-Token": self.app.token, **(headers or {})}
        req = urllib.request.Request(self.url + path, data=json.dumps(obj).encode(), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_repro_migrate_home_path_without_nonce_refused(self):
        from easyread import path_guard
        with tempfile.TemporaryDirectory() as tmp, patch.object(path_guard, "_untrusted_roots", return_value=[]):
            home_like = Path(tmp) / "Documents"  # 受害者自己的資料夾：擁有者檢查會過，只能靠 nonce 擋
            home_like.mkdir()
            for path in ("/api/migrate/scan", "/api/migrate/start"):
                for extra in ({}, {"nonce": "forged"}, {"nonce": ""}):
                    status, body = self._post(path, {"source": "folder", "path": str(home_like), "link": True, **extra})
                    self.assertEqual(status, 400, (path, extra, body))
                    self.assertTrue(any(m in body["error"] for m in ("亲手选", "親手選", "picked yourself")), body)

    def test_picker_nonce_flow_bound_to_path_and_one_time(self):
        from easyread import path_guard
        from easyread.app import folder_pick
        with tempfile.TemporaryDirectory() as tmp, patch.object(path_guard, "_untrusted_roots", return_value=[]):
            picked, other = Path(tmp) / "picked", Path(tmp) / "other"
            picked.mkdir(); other.mkdir()
            with patch.object(folder_pick, "pick", return_value=str(picked)):
                status, r = self._post("/api/library/pick-folder", {"for": "import"})
            self.assertEqual(status, 200)
            nonce = r["nonce"]
            self.assertEqual(self._post("/api/migrate/start", {"source": "folder", "path": str(other), "nonce": nonce})[0], 400)  # 綁定路徑
            self.assertEqual(self._post("/api/migrate/scan", {"source": "folder", "path": str(picked), "nonce": nonce})[0], 200)
            self.assertEqual(self._post("/api/migrate/start", {"source": "folder", "path": str(picked), "nonce": nonce})[0], 200)
            for _ in range(100):
                if self.app.bulk.status.get("state") != "running":
                    break
                threading.Event().wait(0.02)
            self.assertEqual(self._post("/api/migrate/start", {"source": "folder", "path": str(picked), "nonce": nonce})[0], 400)  # 一次性

    def test_picker_title_fixed_server_side_when_issuing_nonce(self):
        from easyread.app import folder_pick
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(folder_pick, "pick", return_value=tmp) as pick:
                status, r = self._post("/api/library/pick-folder", {"for": "import", "title": "選擇備份資料夾（安全）"})
                self.assertEqual(status, 200)
                self.assertTrue(r["nonce"])
                title = pick.call_args[0][0]
                self.assertNotIn("備份", title)  # 頁面給的標題不用
                self.assertTrue(any(m in title for m in ("导入", "匯入", "import")), title)
                status, r = self._post("/api/library/pick-folder", {"title": "選擇備份資料夾"})  # 一般選資料夾：不發授權
                self.assertEqual(status, 200)
                self.assertNotIn("nonce", r)

    def test_zotero_base_comes_from_server_not_request(self):
        from easyread.app import folder_pick
        from easyread.bulk import runner
        from easyread.zotero import locate
        seen = []
        fake_scan = lambda self_, source, where, base="": seen.append(("scan", base)) or {"ok": True}  # noqa: E731
        fake_start = lambda self_, source, where, base="", **k: seen.append(("start", base)) or {"state": "idle"}  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.Migration, "scan", fake_scan), \
                patch.object(runner.Migration, "start", fake_start):
            # 1) 自動偵測到的 Zotero：base 用伺服器偵測到的
            with patch.object(locate, "candidates", return_value=[{"path": tmp, "base": "/Users/me/ZoteroLinked"}]):
                nonce = self._post("/api/zotero/confirm", {"index": 0})[1]["nonce"]
                self.assertEqual(self._post("/api/migrate/scan", {"source": "zotero", "path": tmp, "nonce": nonce, "base": "/"})[0], 200)
                self.assertEqual(self._post("/api/migrate/start", {"source": "zotero", "path": tmp, "nonce": nonce, "base": "/etc"})[0], 200)
            # 2) 自己選的資料夾、不是偵測到的 Zotero：base 為空，請求的 evil base 不用
            with patch.object(locate, "candidates", return_value=[]), patch.object(folder_pick, "pick", return_value=tmp):
                nonce = self._post("/api/library/pick-folder", {"for": "import"})[1]["nonce"]
                self.assertEqual(self._post("/api/migrate/start", {"source": "zotero", "path": tmp, "nonce": nonce, "base": "/Users/victim"})[0], 200)
        self.assertEqual(seen, [("scan", "/Users/me/ZoteroLinked"), ("start", "/Users/me/ZoteroLinked"), ("start", "")])

    def test_desktop_grant_needs_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._post("/api/pick/grant", {"path": tmp})[0], 403)
            self.assertEqual(self._post("/api/pick/grant", {"path": tmp}, {"X-Desktop-Secret": "guess"})[0], 403)
            with patch.object(self.app, "desktop_secret", "s3cret-from-electron"):
                status, r = self._post("/api/pick/grant", {"path": tmp}, {"X-Desktop-Secret": "s3cret-from-electron"})
            self.assertEqual(status, 200)
            self.assertTrue(r["nonce"])

    def test_zotero_confirm_only_server_detected_path(self):
        from easyread.zotero import locate
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(locate, "candidates", return_value=[{"path": tmp}]):
                status, r = self._post("/api/zotero/confirm", {"index": 0, "path": "/Users/victim/Documents"})
                self.assertEqual((status, r["path"]), (200, tmp))  # 帶來的 path 被忽略
                self.assertTrue(r["nonce"])
                for bad in ({"index": 1}, {"index": "0"}, {"path": tmp}):
                    self.assertEqual(self._post("/api/zotero/confirm", bad)[0], 400, bad)

    def test_frontend_no_longer_reads_token_from_json(self):
        bad = re.compile(r"\.token\s*=\s*(d|data|info|res|r)\.token|\)\)\.token|\.json\(\)\)\.token")
        hits = [f"{p}:{i}" for p in WEB_JS.rglob("*.js") for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if bad.search(line)]
        self.assertEqual(hits, [])
        main = (WEB_JS.parents[2] / "electron" / "main.cjs").read_text(encoding="utf-8")
        self.assertNotIn("info.token", main)


if __name__ == "__main__":
    unittest.main()
