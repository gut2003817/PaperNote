from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from easyread.obsidian_context import collect
from easyread.store import Workspace


class ObsidianContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(Path(self.tmp.name))

    def write(self, paper=None, notes=None, item=None):
        data = {
            "paper": paper if paper is not None else {"blocks": []},
            "reader": {"notes": notes or {}},
            "item": item or {},
        }
        for name, value in data.items():
            (self.ws.root / f"{name}.json").write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_collect_marks_have_pages_and_skip_deleted(self):
        self.write({"blocks": [{"id": "b1", "page": 7}, {"id": "b2"}]}, {
            "n1": {"id": "n1", "kind": "highlight", "anchor": "b1",
                   "quote": "原句", "side": "zh", "body": "想法", "page": 99},
            "n2": {"id": "n2", "kind": "highlight", "anchor": "b1",
                   "quote": "已刪除", "deleted": True},
            "n3": {"id": "n3", "kind": "note", "anchor": "b1", "body": "無引用"},
            "n4": {"id": "n4", "kind": "question", "anchor": "b2", "quote": "無頁碼"},
            "n5": {"id": "n5", "kind": "note", "anchor": "missing", "quote": "孤立引用"},
            "n6": {"id": "n6", "kind": "highlight", "anchor": "b1", "quote": ""},
        })
        self.assertEqual(collect(self.ws)["marks"], [
            {"quote": "原句", "page": 7, "side": "zh", "body": "想法"},
            {"quote": "無頁碼", "page": None, "side": "", "body": ""},
            {"quote": "孤立引用", "page": None, "side": "", "body": ""},
        ])

    def test_collect_without_highlights_returns_empty_marks(self):
        for notes in ({}, {"n": {"kind": "note", "body": "純筆記"}}):
            with self.subTest(notes=notes):
                self.write(notes=notes)
                self.assertEqual(collect(self.ws)["marks"], [])

    def test_collect_without_figures(self):
        self.write({"blocks": [{"id": "p1", "page": 1, "type": "para", "zh": "正文"}]})
        self.assertEqual(collect(self.ws)["figures"], [])

    def test_collect_meta_override_wins(self):
        self.write({"meta": {
            "title_en": "Original", "title_zh": "原標題", "authors": "Old Author",
            "year": 2020, "doi": "10.1/old", "url": "https://example.org/old",
        }}, item={"meta_override": {
            "title_en": "Revised", "title_zh": "", "authors": " Alice , Bob, , Carol ",
            "year": 2026, "doi": "10.1/new", "url": "https://example.org/new",
        }})
        ctx = collect(self.ws)
        self.assertEqual((ctx["title"], ctx["authors"], ctx["year"], ctx["source"]),
                         ("Revised", ["Alice", "Bob", "Carol"], "2026", "https://doi.org/10.1/new"))
        self.write({"meta": {"title_zh": "原標題", "doi": "10.1/old", "url": "https://example.org"}},
                   item={"meta_override": {"title_zh": "", "doi": ""}})
        ctx = collect(self.ws)
        self.assertEqual((ctx["title"], ctx["source"]), ("原標題", "https://example.org"))

    def test_collect_missing_year_authors_gives_empty_values(self):
        for paper in ({}, {"meta": {}}, {"meta": {"authors": None, "year": None, "date": None}}):
            with self.subTest(paper=paper):
                self.write(paper)
                self.assertEqual(collect(self.ws), {
                    "title": "", "authors": [], "year": "", "source": "",
                    "marks": [], "figures": [], "text": "",
                })

    def test_collect_marks_sorted_by_block_order(self):
        self.write({"blocks": [{"id": "later_page", "page": 8}, {"id": "earlier_page", "page": 2}]}, {
            "n1": {"anchor": "missing", "quote": "unknown first"},
            "n2": {"anchor": "earlier_page", "quote": "second block"},
            "n3": {"anchor": "later_page", "quote": "first block"},
            "n4": {"anchor": "earlier_page", "quote": "same block"},
            "n5": {"quote": "unknown last"},
        })
        self.assertEqual([m["quote"] for m in collect(self.ws)["marks"]],
                         ["first block", "second block", "same block", "unknown first", "unknown last"])

    def test_collect_text_is_capped(self):
        for blocks, expected in (
            ([{"type": "para", "zh": "譯" * 15000}], "譯" * 14000),
            ([{"type": "para", "zh": "甲" * 7000}, {"type": "para", "zh": "乙" * 7000}],
             "甲" * 7000 + "\n" + "乙" * 6999),
        ):
            with self.subTest(blocks=len(blocks)):
                self.write({"blocks": blocks})
                self.assertEqual(collect(self.ws)["text"], expected)

    def test_collect_figures_and_tables(self):
        self.write({"blocks": [
            {"id": "p1", "type": "para", "page": 1},
            {"id": "f1", "type": "figure", "num": "2a", "page": 3,
             "caption_en": "Architecture", "caption_zh": "架構", "box": [0, 0, 1, 1]},
            {"id": "t1", "type": "table", "num": 1, "page": 4, "caption_zh": "結果"},
            {"id": "f2", "type": "figure", "page": 5, "box": []},
        ]})
        self.assertEqual(collect(self.ws)["figures"], [
            {"id": "f1", "num": "2a", "page": 3, "caption": "Architecture", "type": "figure", "has_box": True},
            {"id": "t1", "num": 1, "page": 4, "caption": "結果", "type": "table", "has_box": False},
            {"id": "f2", "num": None, "page": 5, "caption": "", "type": "figure", "has_box": False},
        ])

    def test_collect_source_priority_and_date_year(self):
        for meta, source in (
            ({"doi": "10.1/paper", "arxiv": "2601.12345", "url": "https://example.org"}, "https://doi.org/10.1/paper"),
            ({"doi": "https://doi.org/10.1/paper"}, "https://doi.org/10.1/paper"),
            ({"arxiv": "2601.12345", "url": "https://example.org"}, "https://arxiv.org/abs/2601.12345"),
            ({"arxiv": "https://arxiv.org/abs/2601.12345v2"}, "https://arxiv.org/abs/2601.12345v2"),
            ({"url": "https://example.org"}, "https://example.org"),
            ({}, ""),
        ):
            with self.subTest(meta=meta):
                self.write({"meta": {"date": "Published 2024-03-02", **meta}})
                ctx = collect(self.ws)
                self.assertEqual(ctx["source"], source)
                self.assertEqual(ctx["year"], "2024")

    def test_collect_text_uses_translation_and_stops_at_references(self):
        self.write({"blocks": [
            {"type": "heading", "zh": "方法", "en": "Method"},
            {"type": "para", "zh": "譯文", "en": "Original"},
            {"type": "para", "en": "Untranslated"},
            {"type": "list", "items": [{"zh": "項目"}, {"en": "Item"}]},
            {"type": "math", "tex": "x=1"},
            {"type": "figure", "id": "f", "page": 2, "caption_en": "Figure", "caption_zh": "圖說",
             "image_en": "Image", "image_zh": "圖中文字"},
            {"type": "references", "en": "References"},
            {"type": "para", "zh": "附錄"},
        ]})
        self.assertEqual(collect(self.ws)["text"], "## 方法\n譯文\nUntranslated\n- 項目\n- Item\n$$x=1$$\n圖說\n圖中文字")

    def test_collect_is_read_only(self):
        self.write({"meta": {"title_en": "Paper"}, "blocks": []})
        before = {p.name: p.read_bytes() for p in self.ws.root.iterdir()}
        collect(self.ws)
        self.assertEqual({p.name: p.read_bytes() for p in self.ws.root.iterdir()}, before)
