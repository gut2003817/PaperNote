import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from easyread.bulk import folder, runner
from easyread.library.library import Library
from tests.zotero.fake_zotero import pdf_bytes


class FolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / "论文"
        for rel, text in [("a.pdf", "a"), ("CV/YOLO/b.pdf", "b"), ("CV/c.PDF", "c"), ("CV/notes.txt", ""), (".hidden/d.pdf", "d"), ("NLP/copy-of-a.pdf", "a")]:
            p = self.src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(pdf_bytes(text) if rel.lower().endswith(".pdf") else b"x")

    def test_folders_become_categories(self):
        snap = folder.read(str(self.src))
        got = {e.pdf.name: e.cats for e in snap.entries}
        self.assertEqual(got, {"a.pdf": ["论文"], "b.pdf": ["论文/CV/YOLO"], "c.PDF": ["论文/CV"], "copy-of-a.pdf": ["论文/NLP"]})
        self.assertEqual(snap.collections, ["论文", "论文/CV", "论文/CV/YOLO", "论文/NLP"])

    def test_missing_folder(self):
        with self.assertRaises(ValueError):
            folder.read(str(self.root / "nope"))

    def test_import_same_pdf_twice_gets_both_categories(self):
        (self.root / "lib").mkdir()
        app = MagicMock()
        app.lib = Library(self.root / "lib")
        saved = {}
        with patch.object(runner.threading, "Thread", lambda target, args, daemon: MagicMock(start=lambda: target(*args))), \
                patch.object(runner.prefs, "load", return_value={}), patch.object(runner.prefs, "save", side_effect=saved.update):
            st = runner.Migration(app).start("folder", str(self.src))
        self.assertEqual((st["state"], st["imported"], st["existing"]), ("done", 3, 1))
        tags = sorted(sorted(ws.load("item")["tags"]) for ws in app.lib.all())
        self.assertIn(["论文", "论文/NLP"], tags)  # 两个文件夹里是同一个 PDF：一篇论文，两个分类
        self.assertEqual(saved["library"]["cats"], ["论文", "论文/CV", "论文/CV/YOLO", "论文/NLP"])


if __name__ == "__main__":
    unittest.main()
