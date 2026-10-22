import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.zotero import locate, reader
from tests.zotero.fake_zotero import FakeZotero


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.z = FakeZotero(Path(self.tmp.name))
        self.addCleanup(self.z.close)

    def read(self):
        self.z.close()
        return reader.read(self.tmp.name)

    def test_metadata_authors_collections_and_tags(self):
        z = self.z
        a = z.item(title="Attention Is All You Need", date="2017-06-00 June 2017", publicationTitle="NeurIPS",
                   DOI="https://doi.org/10.5555/x", url="https://arxiv.org/abs/1706.03762v5", abstractNote="We propose...")
        z.author(a, "Ashish", "Vaswani", 0)
        z.author(a, "", "Google Brain", 1, single=True)
        z.author(a, "Ed", "Itor", 2, kind=2)
        z.pdf(a, "attention")
        ml = z.collection("ML")
        nlp = z.collection("NLP/Text", parent=ml)
        z.put(nlp, a)
        z.tag(a, "必读")
        z.tag(a, "Computer Science - Computation and Language", auto=True)
        snap = self.read()
        e = snap.entries[0]
        self.assertEqual(e.meta["title_en"], "Attention Is All You Need")
        self.assertEqual(e.meta["authors"], "Ashish Vaswani, Google Brain")  # 编者不算作者
        self.assertEqual((e.meta["date"], e.meta["year"]), ("2017-06", "2017"))
        self.assertEqual(e.meta["venue"], "NeurIPS")
        self.assertEqual(e.meta["doi"], "10.5555/x")
        self.assertEqual(e.meta["arxiv"], "arXiv:1706.03762")
        self.assertEqual(e.cats, ["ML/NLP／Text"])  # 名字里的 / 不能变成层级
        self.assertEqual(e.tags, ["必读"])  # 自动标签不要
        self.assertEqual(e.added, "2023-01-02T03:04:05+00:00")
        self.assertTrue(e.pdf and e.pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(snap.collections, ["ML", "ML/NLP／Text"])

    def test_trash_missing_files_and_standalone_pdfs(self):
        z = self.z
        gone = z.item(title="In trash")
        z.pdf(gone)
        z.trash(gone)
        nofile = z.item(title="No PDF")
        broken = z.item(title="Broken link")
        aid = z.pdf(broken, "x")
        (Path(self.tmp.name) / "storage" / f"KEY{aid:05d}" / "paper.pdf").unlink()
        lone = z.pdf(None, "lone", name="Some Paper.pdf")
        z.item("note", title="a note")
        es = {e.meta.get("title_en"): e for e in self.read().entries}
        self.assertNotIn("In trash", es)
        self.assertNotIn("a note", es)
        self.assertIsNone(es["No PDF"].pdf)
        self.assertTrue(es["No PDF"].missing)
        self.assertIsNone(es["Broken link"].pdf)
        self.assertIn("paper.pdf", es["Broken link"].missing)
        self.assertTrue(es["Some Paper"].pdf)  # 没有父条目的 PDF 自己算一条，标题用文件名
        self.assertTrue(lone)

    def test_group_library_collections_go_under_group_name(self):
        z = self.z
        z.group(2, "Lab")
        c = z.collection("Shared", lib=2)
        i = z.item(lib=2, title="Group paper")
        z.put(c, i)
        snap = self.read()
        self.assertEqual(snap.entries[0].cats, ["Lab/Shared"])

    def test_locked_database_falls_back_to_backup(self):
        z = self.z
        z.item(title="x")
        z.close()
        root = Path(self.tmp.name)
        (root / "zotero.sqlite.bak").write_bytes((root / "zotero.sqlite").read_bytes())
        real = reader.shutil.copyfile

        def locked(src, dst):
            if Path(src).name == "zotero.sqlite":
                raise PermissionError("locked")
            return real(src, dst)
        with patch.object(reader.shutil, "copyfile", side_effect=locked):
            self.assertTrue(reader.read(root).from_backup)

    def test_not_a_zotero_folder(self):
        self.z.close()
        with self.assertRaises(ValueError):
            reader.read(Path(self.tmp.name) / "storage")

    def test_prefs_paths_unescape(self):
        text = 'user_pref("extensions.zotero.dataDir", "D:\\\\论文\\\\Zot \\"x\\"");'
        self.assertEqual(locate._pref(text, "extensions.zotero.dataDir"), 'D:\\论文\\Zot "x"')


if __name__ == "__main__":
    unittest.main()
