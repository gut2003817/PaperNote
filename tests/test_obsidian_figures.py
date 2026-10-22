"""Obsidian 附图：真实 PDF 裁剪、可读命名、重用与不覆盖。"""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from easyread import obsidian_figures
from easyread.pdf import pdfwork
from easyread.app.i18n import tr
from easyread.library.store import Workspace


class ObsidianFiguresTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = Workspace(self.root)
        self.attach = self.root / "附圖"
        self.attach.mkdir()
        # 沿用 figure_geometry 的 PdfWriter + 内容流，第二页左上角为红色。
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=80)
        page = writer.add_blank_page(width=100, height=80)
        stream = DecodedStreamObject()
        stream.set_data(b"1 0 0 rg 0 40 50 40 re f")
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(self.root / "source.pdf")
        self.block = {"id": "fig2", "type": "figure", "num": 2,
                      "page": 2, "box": [0, 0, .5, .5]}
        # tr 不读取真实 prefs.json。
        language = patch.dict("os.environ", {"EASYREAD_LANG": "zh-TW"})
        language.start()
        self.addCleanup(language.stop)

    def export(self, block=None, short="6G-SAGIN", desc="整體架構"):
        return obsidian_figures.export_figure(
            self.ws, self.block if block is None else block, short, desc, self.attach)

    def test_crop_png_returns_png_bytes(self):
        before = set(self.root.rglob("*"))
        for scale, size in ((3.0, (150, 120)), (2.0, (100, 80))):
            with self.subTest(scale=scale):
                data = pdfwork.crop_png(self.root, 2, self.block["box"], scale=scale)
                self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                with Image.open(BytesIO(data)) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.getpixel((20, 20)), (255, 0, 0))
        self.assertEqual(set(self.root.rglob("*")), before)

    def test_crop_keeps_webp_behaviour(self):
        rel = pdfwork.crop(self.root, 2, self.block["box"], "figure-2")
        self.assertEqual(rel, "figures/figure-2.webp")
        with Image.open(self.root / rel) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (150, 120))
            self.assertGreater(image.getpixel((20, 20))[0], 240)
        rel = pdfwork.crop(self.root, 1, [0, 0, 1, 1], "small", scale=1.0)
        with Image.open(self.root / rel) as image:
            self.assertEqual(image.size, (100, 80))

    def test_export_figure_names_file_readably(self):
        name = self.export()
        self.assertEqual(name, "6G-SAGIN-圖2-整體架構.png")
        self.assertEqual((self.attach / name).read_bytes(),
                         pdfwork.crop_png(self.root, 2, self.block["box"]))
        block = {key: value for key, value in self.block.items() if key != "num"}
        self.assertEqual(self.export(block), "6G-SAGIN-圖x-整體架構.png")

    def test_export_figure_same_content_is_reused(self):
        name = self.export()
        path = self.attach / name
        before = path.stat()
        self.assertEqual(self.export(), name)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(list(self.attach.iterdir()), [path])

    def test_export_figure_different_content_gets_suffix_not_overwritten(self):
        name = self.export()
        path = self.attach / name
        before = path.read_bytes()
        other = {**self.block, "page": 1}
        second = self.export(other)
        self.assertEqual(second, "6G-SAGIN-圖2-整體架構-2.png")
        self.assertNotEqual((self.attach / second).read_bytes(), before)
        self.assertEqual(self.export(other), second)
        third = self.export({**other, "box": [0, 0, 1, 1]})
        self.assertEqual(third, "6G-SAGIN-圖2-整體架構-3.png")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(self.attach.iterdir())), 3)

    def test_export_figure_without_box_raises(self):
        for block in ({"page": 1}, {"page": 1, "box": []}, {"page": 1, "box": None}):
            with self.subTest(block=block), patch.object(pdfwork, "crop_png") as crop:
                with self.assertRaises(ValueError) as error:
                    self.export(block)
                self.assertEqual(str(error.exception), tr("图片内容无法识别"))
                crop.assert_not_called()
        self.assertEqual(list(self.attach.iterdir()), [])

    def test_export_figure_cjk_and_special_chars_in_names(self):
        name = self.export(short='中文 /論文:*?"<>|\\', desc="系統 架構/圖:\n")
        self.assertEqual(name, "中文-論文-圖2-系統-架構圖.png")
        self.assertEqual((self.attach / name).parent, self.attach)
        self.assertTrue((self.attach / name).is_file())
        self.assertEqual(self.export(short="", desc=""), "paper-圖2-paper.png")
        # 图号也不能带路径分隔符。
        unsafe = self.export({**self.block, "num": "2/../../escape"})
        self.assertEqual(Path(unsafe).name, unsafe)
        self.assertTrue((self.attach / unsafe).is_file())
