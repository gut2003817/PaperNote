"""设置键 obsidian_vault：默认空，非空必须通过 check_vault，不合格整个 patch 不写盘。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread import config, settings_api


class ObsidianSettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg_path = self.root / "config.json"
        p = patch.object(config, "CONFIG_PATH", self.cfg_path)
        p.start()
        self.addCleanup(p.stop)

    def test_default_vault_is_empty(self):
        self.assertEqual(config.DEFAULTS["obsidian_vault"], "")
        self.assertEqual(config.load()["obsidian_vault"], "")

    def test_save_config_accepts_valid_vault(self):
        vault = self.root / "vault"
        vault.mkdir()
        out = settings_api.save_config({"obsidian_vault": str(vault)})
        self.assertEqual(out["config"]["obsidian_vault"], str(vault))
        self.assertEqual(json.loads(self.cfg_path.read_text("utf-8"))["obsidian_vault"], str(vault))
        self.assertEqual(sorted(p.name for p in vault.iterdir()), [])  # 验证只探测可写，不留东西

    def test_save_config_rejects_bad_vault_and_writes_nothing(self):
        self.cfg_path.write_text(json.dumps({"page_cap": 10}), "utf-8")
        os.utime(self.cfg_path, (1_000_000, 1_000_000))
        before = (self.cfg_path.read_bytes(), self.cfg_path.stat().st_mtime_ns)
        file = self.root / "afile"
        file.write_text("x")
        for bad in ("relative/path", str(self.root / "missing"), str(file)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings_api.save_config({"obsidian_vault": bad, "page_cap": 99})  # 同一 patch 里的合法项也不能写
            self.assertEqual((self.cfg_path.read_bytes(), self.cfg_path.stat().st_mtime_ns), before)

    def test_bad_vault_on_fresh_install_creates_no_config(self):
        with self.assertRaises(ValueError):
            settings_api.save_config({"obsidian_vault": "nope"})
        self.assertFalse(self.cfg_path.exists())

    def test_empty_vault_allowed(self):
        vault = self.root / "vault"
        vault.mkdir()
        settings_api.save_config({"obsidian_vault": str(vault)})
        out = settings_api.save_config({"obsidian_vault": ""})
        self.assertEqual(out["config"]["obsidian_vault"], "")

    def test_vault_with_space_ok(self):
        vault = self.root / "Obsidian Vault"
        vault.mkdir()
        out = settings_api.save_config({"obsidian_vault": str(vault)})
        self.assertEqual(out["config"]["obsidian_vault"], str(vault))

    def test_non_string_vault_rejected(self):
        with self.assertRaises(ValueError):
            settings_api.save_config({"obsidian_vault": 5})
        self.assertFalse(self.cfg_path.exists())


if __name__ == "__main__":
    unittest.main()
