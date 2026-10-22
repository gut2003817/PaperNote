"""界面语言：系统语言判断、tr 填占位符、页面注入词典，以及所有界面文字都有英文。  python -m unittest tests.app.test_i18n"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from easyread.app import i18n

ROOT = Path(__file__).resolve().parents[2]


class I18nTest(unittest.TestCase):
    def setUp(self):
        i18n.system_lang.cache_clear()

    def tearDown(self):
        i18n.system_lang.cache_clear()

    def test_system_lang_from_electron(self):
        # 繁体地区统一是 "zh-TW"（上游叫 zh-Hant，繁體版当别名），zh-Hans-HK 仍是简体
        for tag, want in (("zh-CN", "zh"), ("zh-TW", "zh-TW"), ("zh-HK", "zh-TW"), ("zh-Hant", "zh-TW"), ("zh-Hans-HK", "zh"), ("en-US", "en"), ("de", "en"), ("ja", "en")):
            i18n.system_lang.cache_clear()
            with mock.patch.dict(os.environ, {"EASYREAD_SYSTEM_LANG": tag}):
                self.assertEqual(i18n.system_lang(), want, tag)

    def test_system_lang_traditional(self):
        cases = (
            ("zh-TW", "zh-TW"), ("zh_TW", "zh-TW"), ("zh-tw", "zh-TW"), ("zh-Hant", "zh-TW"), ("zh-Hant-TW", "zh-TW"),
            ("zh-HK", "zh-TW"), ("zh-MO", "zh-TW"), ("zh-Hant-HK", "zh-TW"), ("zh_TW.UTF-8", "zh-TW"),
            ("zh-CN", "zh"), ("zh-Hans", "zh"), ("zh-Hans-CN", "zh"), ("zh-SG", "zh"), ("zh", "zh"), ("zh_CN.UTF-8", "zh"),
            ("en-US", "en"), ("ja-JP", "en"),
        )
        for tag, want in cases:
            i18n.system_lang.cache_clear()
            with mock.patch.dict(os.environ, {"EASYREAD_SYSTEM_LANG": tag}):
                self.assertEqual(i18n.system_lang(), want, tag)

    def test_system_lang_macos_apple_languages(self):
        env = {k: v for k, v in os.environ.items() if k not in ("EASYREAD_SYSTEM_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")}
        for first, want in (("zh-Hant-TW", "zh-TW"), ("zh-Hant-HK", "zh-TW"), ("zh-Hans-CN", "zh"), ("en-TW", "en")):
            i18n.system_lang.cache_clear()
            out = f'(\n    "{first}",\n    "en-US"\n)\n'
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(i18n.sys, "platform", "darwin"), \
                    mock.patch.object(i18n.subprocess, "run", lambda *a, **k: mock.Mock(stdout=out)):
                self.assertEqual(i18n.system_lang(), want, first)

    def test_choice_accepts_zh_tw(self):
        with mock.patch.dict(os.environ, {"EASYREAD_LANG": "zh-TW"}):
            self.assertEqual(i18n.choice(), "zh-TW")
            self.assertEqual(i18n.lang(), "zh-TW")
        with mock.patch.dict(os.environ, {"EASYREAD_LANG": "xx"}), mock.patch("easyread.app.prefs.load", lambda: {"ui": {"lang": "zh-TW"}}):
            self.assertEqual(i18n.choice(), "zh-TW")
        self.assertIn("zh-TW", i18n.CHOICES)

    def test_system_lang_from_env(self):
        env = {k: v for k, v in os.environ.items() if k not in ("EASYREAD_SYSTEM_LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE")}
        env["LANG"] = "de_DE.UTF-8"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(i18n.system_lang(), "en")

    def test_choice_overrides_system(self):
        with mock.patch.object(i18n, "system_lang", lambda: "zh"), mock.patch.object(i18n, "choice", lambda: "en"):
            self.assertEqual(i18n.lang(), "en")
        with mock.patch.object(i18n, "system_lang", lambda: "en"), mock.patch.object(i18n, "choice", lambda: "auto"):
            self.assertEqual(i18n.lang(), "en")

    def test_tr(self):
        fake = {"已导入 {n} 篇": "Imported {n} papers"}
        with mock.patch.object(i18n, "en_dict", lambda: fake):
            with mock.patch.object(i18n, "lang", lambda: "en"):
                self.assertEqual(i18n.tr("已导入 {n} 篇", n=3), "Imported 3 papers")
                self.assertEqual(i18n.tr("词典里没有"), "词典里没有")
            with mock.patch.object(i18n, "lang", lambda: "zh"):
                self.assertEqual(i18n.tr("已导入 {n} 篇", n=3), "已导入 3 篇")

    def test_tr_zh_tw(self):
        fake = {"设置": "設定", "已导入 {n} 篇": "已匯入 {n} 篇"}
        with mock.patch.object(i18n, "zhtw_dict", lambda: fake), mock.patch.object(i18n, "lang", lambda: "zh-TW"):
            self.assertEqual(i18n.tr("已导入 {n} 篇", n=3), "已匯入 3 篇")
            self.assertEqual(i18n.tr("设置"), "設定")
            self.assertEqual(i18n.tr("词典里没有 {n}", n=1), "词典里没有 1")  # 查不到退回简体原文，不报错

    def test_zhtw_dict_matches_en_keys(self):
        en = json.loads(i18n.EN_PATH.read_text(encoding="utf-8"))
        tw = json.loads(i18n.ZHTW_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(tw), set(en))
        self.assertEqual([k for k in tw if not isinstance(tw[k], str) or not tw[k].strip()], [])

    def test_zhtw_real_dict_is_traditional_taiwan(self):
        with mock.patch.object(i18n, "lang", lambda: "zh-TW"):
            self.assertEqual(i18n.tr("设置"), "設定")
            self.assertEqual(i18n.tr("导入"), "匯入")
            self.assertEqual(i18n.tr("默认"), "預設")
            self.assertEqual(i18n.tr("文献库"), "文獻庫")
            self.assertEqual(i18n.tr("已导入 {n} 篇", n=3), "已匯入 3 篇")
        # 占位符一个不能少：{n}、{msg} 这类花括号变量在繁体词条里必须原样保留
        import re
        en = json.loads(i18n.EN_PATH.read_text(encoding="utf-8"))
        tw = json.loads(i18n.ZHTW_PATH.read_text(encoding="utf-8"))
        ph = re.compile(r"\{\w+\}")
        self.assertEqual([k for k in en if sorted(ph.findall(k)) != sorted(ph.findall(tw[k]))], [])

    def test_inject_zh_tw(self):
        page = '<html lang="zh-CN">\n<head><title>EasyRead</title></head>'
        with mock.patch.object(i18n, "zhtw_dict", lambda: {"设置": "設定</script>"}):
            out = i18n.inject(page, "zh-TW")
        self.assertIn('<html lang="zh-TW"', out)
        self.assertIn('id="pr-i18n"', out)
        self.assertNotIn("設定</script>", out)  # < 要转义
        self.assertIn("\\u003c", out)

    def test_inject(self):
        page = '<html lang="zh-CN">\n<head><title>EasyRead</title></head>'
        self.assertNotIn("pr-i18n", i18n.inject(page, "zh"))
        with mock.patch.object(i18n, "en_dict", lambda: {"设置": "Settings</script>"}):
            out = i18n.inject(page, "en")
        self.assertIn('<html lang="en"', out)
        self.assertIn('id="pr-i18n"', out)
        self.assertNotIn("Settings</script>", out)  # 词典里的 < 要转义，不能提前结束 script

    def test_every_ui_string_has_english(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n_check.py")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout[-3000:])

    def test_traditional_interface_dictionary_and_injection(self):
        # 上游的 zh-Hant 在繁體版是 zh-TW 的别名：词典用 zh-TW.json，页面 lang 写 zh-TW
        traditional = i18n.ui_dict("zh-Hant")
        for key in i18n.en_dict():
            self.assertTrue(traditional.get(key), key)
            self.assertEqual(re.findall(r"\{\w+\}", key), re.findall(r"\{\w+\}", traditional[key]), key)
        with mock.patch.object(i18n, "lang", lambda: "zh-Hant"):
            self.assertEqual(i18n.tr("设置"), "設定")
        out = i18n.inject('<html lang="zh-CN"><head><title>EasyRead</title></head>', "zh-Hant")
        self.assertIn('<html lang="zh-TW"', out)
        self.assertIn('id="pr-i18n"', out)


if __name__ == "__main__":
    unittest.main()
