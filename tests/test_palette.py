"""配色偏好：服务器端校验（真的起服务、走 POST /api/prefs）、往返读写、前后端 preset 清单对账、离线导出。
    python -m unittest tests.test_palette
"""
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread import build, launch, palette, prefs, server
from tests.test_hostcheck import MINI_PDF, raw

WEB = Path(__file__).resolve().parents[1] / "easyread" / "web"

ATTACKS = [
    {"light": {"custom": {"bg": "red;}</style><script>alert(1)</script>", "ink": "#000000"}}},
    {"light": {"custom": {"bg": "#ffffff;}</style><script>alert(1)</script>", "ink": "#000000"}}},
    {"light": {"custom": {"bg": "#ffffff", "ink": "#000000\n"}}},       # $ 会放过的结尾换行
    {"light": {"custom": {"bg": "#fff", "ink": "#000"}}},
    {"light": {"custom": {"bg": "url(javascript:alert(1))", "ink": "#000000"}}},
    {"light": {"custom": {"bg": "#ffffff", "ink": "#000000", "x": "#111111"}}},
    {"light": {"custom": {"bg": 0xFFFFFF, "ink": "#000000"}}},
    {"light": {"custom": {"bg": None, "ink": "#000000"}}},
    {"light": {"custom": {"bg": ["#ffffff"], "ink": "#000000"}}},
    {"light": {"preset": "<img src=x onerror=alert(1)>"}},
    {"light": {"preset": "nope"}},
    {"light": {"preset": "oled"}},                                         # 深色的 id 不能用在浅色
    {"dark": {"preset": "white"}},
    {"light": {"preset": ["default"]}},
    {"light": {"preset": "white", "custom": {"bg": "#ffffff", "ink": "#000000"}}},
    {"light": {}},
    {"light": "white"},
    {"sepia": {"preset": "white"}},
    {"__proto__": {"preset": "white"}},
    {"light": {"custom": {"bg": "#ffffff", "ink": "#f0f0f0"}}},             # 对比度 < 3:1
    "light", ["light"], 5,
]


class PrefsUnitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip(self):
        pal = {"light": {"preset": "green"}, "dark": {"custom": {"bg": "#101820", "ink": "#E0E8F0"}}}
        out = prefs.save({"reader": {"theme": "dark", "palette": pal}})
        self.assertEqual(out["reader"]["palette"], {"light": {"preset": "green"}, "dark": {"custom": {"bg": "#101820", "ink": "#e0e8f0"}}})
        self.assertEqual(prefs.load()["reader"]["palette"], out["reader"]["palette"])
        self.assertEqual(prefs.load()["reader"]["theme"], "dark")

    def test_rejects_all_attacks_and_writes_nothing(self):
        prefs.save({"reader": {"fs": 18}})
        before = prefs.load()
        for bad in ATTACKS:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                prefs.save({"reader": {"fs": 99, "palette": bad}})
        self.assertEqual(prefs.load(), before)  # 整个请求都没落盘（fs 也没被改成 99）

    def test_clear_and_default(self):
        prefs.save({"reader": {"palette": {"light": {"preset": "white"}}}})
        self.assertEqual(prefs.save({"reader": {"palette": {}}})["reader"]["palette"], {})
        self.assertEqual(prefs.save({"reader": {"palette": {"dark": {"preset": "default"}}}})["reader"]["palette"], {"dark": {"preset": "default"}})

    def test_hand_edited_bad_file_is_not_served(self):
        prefs.path().write_text(json.dumps({"reader": {"theme": "dark", "palette": {"light": {"custom": {"bg": "x;}", "ink": "#000000"}}}}}))
        r = prefs.load()["reader"]
        self.assertNotIn("palette", r)
        self.assertEqual(r["theme"], "dark")

    def test_preset_ids_match_frontend(self):
        js = (WEB / "js/common/palette.js").read_text(encoding="utf-8")
        for mode in ("light", "dark"):
            block = re.search(mode + r": \[(.*?)\n    \]", js, re.S).group(1)
            self.assertEqual(tuple(re.findall(r'id: "(\w+)"', block)), palette.PRESET_IDS[mode], mode)

    def test_front_and_back_contrast_agree(self):
        self.assertEqual(round(palette.contrast("#000000", "#ffffff"), 2), 21.0)
        self.assertEqual(round(palette.contrast("#767676", "#ffffff"), 2), 4.54)


class PrefsHttpTest(unittest.TestCase):
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
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.cfg.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def post(self, obj, token=True):
        body = json.dumps(obj).encode()
        h = {"Content-Type": "application/json", **({"X-Token": self.app.token} if token else {})}
        return raw(self.port, "POST", "/api/prefs", f"127.0.0.1:{self.port}", h, body)

    def get(self):
        s, _, c = raw(self.port, "GET", "/api/prefs", f"127.0.0.1:{self.port}", {"X-Token": self.app.token})
        return s, json.loads(c)

    def test_http_roundtrip_and_attacks(self):
        good = {"light": {"preset": "parchment"}, "dark": {"custom": {"bg": "#000000", "ink": "#ffffff"}}}
        s, _, c = self.post({"reader": {"palette": good}})
        self.assertEqual(s, 200, c)
        self.assertEqual(self.get()[1]["reader"]["palette"], good)
        for bad in ATTACKS:
            s, _, c = self.post({"reader": {"palette": bad}})
            self.assertEqual(s, 400, (bad, c))
            self.assertIn("error", json.loads(c))
        self.assertEqual(self.get()[1]["reader"]["palette"], good)  # 攻击之后原值不变
        self.assertEqual(self.post({"reader": {"palette": good}}, token=False)[0], 403)  # token 校验没被放宽

    def test_export_carries_palette_only_as_validated_data(self):
        ws, _ = self.app.lib.create_from_pdf(MINI_PDF, "x.pdf", {"title_en": "T"})
        self.post({"reader": {"palette": {"light": {"preset": "white"}}}})
        page = build.build(ws, Path(self.tmp.name) / "o.html").read_text(encoding="utf-8")
        self.assertIn('window.ER_PALETTE_EXPORT={"light": {"preset": "white"}};', page)
        self.assertNotIn("<style>:root{--bg", page)
        # 没设配色时，导出页不带这段
        self.post({"reader": {"palette": {}}})
        page = build.build(ws, Path(self.tmp.name) / "o2.html").read_text(encoding="utf-8")
        self.assertNotIn("window.ER_PALETTE_EXPORT={", page)


if __name__ == "__main__":
    unittest.main()
