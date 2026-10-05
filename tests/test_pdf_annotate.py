"""导出带划线的 PDF（easyread/pdf_annotate.py）。

fixture 是测试里即时生成的最小 PDF（纯 ASCII、Helvetica）：多行、换行连字号、两栏、跨页段落、
CropBox 偏移、旋转 90 度的页、已有的链接和书签。用 pdfwork.extract_text 抽字产生 extract/*.chars.json，
走和真实论文一样的管线。验证注解位置时，用 PDFium 重新抽字（紧字框，PDF 用户空间），取落在每个 quad 里的字。
    python -m pytest tests/test_pdf_annotate.py -q
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import socket
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pypdf
import pypdfium2 as pdfium

from easyread import pdf_annotate as pa
from easyread import pdfwork, sentences
from easyread.i18n import tr

FONT = 10
LEAD = 14


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(lines, rotated=False) -> bytes:
    out = []
    for x, y, text in lines:
        tm = f"0 1 -1 0 {x} {y} Tm" if rotated else f"1 0 0 1 {x} {y} Tm"
        out.append(f"BT /F1 {FONT} Tf {tm} ({_esc(text)}) Tj ET")
    return "\n".join(out).encode("ascii")


def make_pdf(pages: list[dict]) -> bytes:
    """pages: [{"lines": [(x, y, text)], "rotate": 0, "crop": [..] | None, "link": [x0, y0, x1, y1] | None}]。
    额外加两层书签（指向第 1、2 页）。"""
    objs: dict[int, bytes] = {}
    n_pages = len(pages)
    font, outlines = 3, 4
    first_page = 7
    page_ids = [first_page + 2 * i for i in range(n_pages)]
    objs[1] = f"<< /Type /Catalog /Pages 2 0 R /Outlines {outlines} 0 R /PageMode /UseOutlines >>".encode()
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n_pages} >>".encode()
    objs[font] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objs[outlines] = b"<< /Type /Outlines /First 5 0 R /Last 6 0 R /Count 2 >>"
    objs[5] = f"<< /Title (Part one) /Parent {outlines} 0 R /Next 6 0 R /Dest [{page_ids[0]} 0 R /XYZ 0 792 0] >>".encode()
    objs[6] = f"<< /Title (Part two) /Parent {outlines} 0 R /Prev 5 0 R /Dest [{page_ids[min(1, n_pages - 1)]} 0 R /XYZ 0 792 0] >>".encode()
    nxt = first_page + 2 * n_pages
    for i, pg in enumerate(pages):
        pid, cid = page_ids[i], page_ids[i] + 1
        data = _content(pg["lines"], rotated=pg.get("rotate") == 90)
        objs[cid] = b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"
        extra = ""
        if pg.get("crop"):
            extra += " /CropBox [%s]" % " ".join(str(v) for v in pg["crop"])
        if pg.get("rotate"):
            extra += f" /Rotate {pg['rotate']}"
        if pg.get("link"):
            lid = nxt
            nxt += 1
            objs[lid] = ("<< /Type /Annot /Subtype /Link /Rect [%s] /Border [0 0 0] /A << /S /URI /URI (https://example.org/) >> >>"
                         % " ".join(str(v) for v in pg["link"])).encode()
            extra += f" /Annots [{lid} 0 R]"
        objs[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]{extra} "
                     f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {cid} 0 R >>").encode()
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = {}
    for k in sorted(objs):
        offsets[k] = buf.tell()
        buf.write(f"{k} 0 obj\n".encode() + objs[k] + b"\nendobj\n")
    xref = buf.tell()
    size = max(objs) + 1
    buf.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for k in range(1, size):
        buf.write(f"{offsets[k]:010d} 00000 n \n".encode() if k in offsets else b"0000000000 65535 f \n")
    buf.write(f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return buf.getvalue()


def aligned(en_sents: list[str], zh_sents: list[str]) -> tuple[str, str, list]:
    """英文句子用空格接、中文直接接，sents 按 UTF-16 句尾（和 sentences.unmark 同一规则）。"""
    en, zh, rows = "", "", []
    for i, (e, z) in enumerate(zip(en_sents, zh_sents)):
        if i:
            rows.append([sentences.u16(en), sentences.u16(zh)])
            en += " "
        en += e
        zh += z
    rows.append([sentences.u16(en), sentences.u16(zh)])
    return en, zh, rows


# ---------- 段落内容 ----------
A_EN = ["Graph models detect intrusions quickly.", "**Robust** detectors keep the network secure against new attacks.",
        "We test $x_i$ features in practice."]
A_ZH = ["图模型\U0001D465能很快发现入侵。", "稳健的检测器让网络抵御新攻击。", "我们在实践中测试 $x_i$ 特征。"]  # 第一句带补充平面字符：UTF-16 占 2
ITEM0_EN, ITEM0_ZH = ["First item explains the detection pipeline."], ["第一项说明检测流程。"]
ITEM1_EN, ITEM1_ZH = ["Second item covers the response stage.", "It ends with a short summary."], ["第二项讲响应阶段。", "最后有简短总结。"]
X_EN = ["Cross page paragraphs begin near the bottom of the right column and continue on the next page with more words.",
        "The second sentence finishes the cross page paragraph."]
X_ZH = ["跨页段落从右栏底部开始，接到下一页继续。", "第二句结束这个跨页段落。"]
U_EN = "Unaligned paragraph text stays whole when highlighted by the reader."
U_ZH = "没有句子对齐的段落整段标出。"
E_EN, E_ZH, E_S = aligned(["Edited paragraph one is here.", "Edited paragraph two follows it."], ["改过的第一句。", "改过的第二句。"])
P_PRINTED = "Partial print paragraph keeps its words."
P_EN, P_ZH = P_PRINTED + " Then a bend.", "只印了一部分的段落。"
R_EN, R_ZH, R_S = aligned(["Rotated pages keep their highlights aligned.", "Readers rotate scanned pages often."],
                          ["旋转页的划线也对得上。", "读者常旋转扫描页。"])

PAGE1 = [  # 左栏：段落 A（含 se-/cure 连字号断行）；右栏：列表两项 + 跨页段落开头
    (72, 700, "Graph models detect intrusions quickly. Robust"),
    (72, 686, "detectors keep the network se-"),
    (72, 672, "cure against new attacks. We test xi features"),
    (72, 658, "in practice."),
    (330, 700, "First item explains the detection pipeline."),
    (330, 672, "Second item covers the response stage. It ends"),
    (330, 658, "with a short summary."),
    (330, 120, "Cross page paragraphs begin near the bottom"),
    (330, 106, "of the right column and continue"),
    (330, 70, "Figure 9. The scenarios on the next page and the corresponding threats."),  # 字符流里紧跟在段落后面的题注
]
PAGE2 = [
    (72, 760, "Fixture Journal 2026 Page 2"),  # 页眉：跨页段落中间多出来的字
    # 下一页先排一大块边栏（字符流里在接续文字前面、超过 600 个字母）：段尾不在页首附近
    *[(330, 745 - 12 * i, f"Sidebar {i}: the next page begins with figure words and more") for i in range(14)],
    (72, 720, "on the next page with more words. The second"),
    (72, 706, "sentence finishes the cross page paragraph."),
    (72, 660, "Unaligned paragraph text stays whole when"),
    (72, 646, "highlighted by the reader."),
    (72, 600, "Edited paragraph one is here. Edited"),
    (72, 586, "paragraph two follows it."),
    (72, 540, "Partial print paragraph keeps its words."),  # 英文末句没印出来（P_EN 多一句）
    (72, 526, "Junk: the cat has a bend radius."),  # 字符流里紧跟着的无关文字，含零星可巧合的字母
]
PAGE3 = [  # /Rotate 90：字沿用户空间 +y 方向写，显示时是正的；下一行往 +x
    (150, 100, "Rotated pages keep their highlights aligned."),
    (164, 100, "Readers rotate scanned pages often."),
]


def build_paper(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pdf = make_pdf([
        {"lines": PAGE1, "crop": [20, 30, 592, 772]},
        {"lines": PAGE2, "link": [72, 640, 300, 670]},
        {"lines": PAGE3, "rotate": 90},
    ])
    (root / "source.pdf").write_bytes(pdf)
    pdfwork.extract_text(root / "source.pdf", root / "extract")
    a_en, a_zh, a_s = aligned(A_EN, A_ZH)
    i0 = dict(zip(("en", "zh", "sents"), aligned(ITEM0_EN, ITEM0_ZH)))
    i0.pop("sents")  # 只有一句：没有 sents
    i1 = dict(zip(("en", "zh", "sents"), aligned(ITEM1_EN, ITEM1_ZH)))
    x_en, x_zh, x_s = aligned(X_EN, X_ZH)
    blocks = [
        {"id": "p1-0", "type": "para", "page": 1, "en": a_en, "zh": a_zh, "sents": a_s},
        {"id": "p1-1", "type": "list", "page": 1, "items": [i0, i1]},
        {"id": "p1-2", "type": "para", "page": 1, "en": x_en, "zh": x_zh, "sents": x_s},
        {"id": "p2-0", "type": "para", "page": 2, "en": U_EN, "zh": U_ZH},
        {"id": "p2-1", "type": "para", "page": 2, "en": E_EN, "zh": E_ZH, "sents": E_S},
        {"id": "p2-2", "type": "para", "page": 2, "en": P_EN, "zh": P_ZH},
        {"id": "p3-0", "type": "para", "page": 3, "en": R_EN, "zh": R_ZH, "sents": R_S},
    ]
    paper = {"schema": 1, "meta": {"title_en": 'Fixture: A "Tiny" Paper/Test', "title_zh": "测试"}, "blocks": blocks}
    (root / "paper.json").write_text(json.dumps(paper, ensure_ascii=False), encoding="utf-8")
    write_reader(root, default_notes())
    pdfwork.locate(root)


def note(nid, anchor, key, quote, side=None, **kw):
    n = {"id": nid, "anchor": anchor, "key": key, "quote": quote, "prefix": "", "suffix": "", "kind": "highlight",
         "color": "yellow", "created": "2026-10-06T10:00:00+08:00", "updated": "2026-10-06T10:00:00+08:00"}
    if side:
        n["side"] = side
    n.update(kw)
    return n


def default_notes():
    return [
        note("zh-sent", "p1-0", "p1-0", "稳健"),  # 译文第 2 句开头 → 英文第 2 句
        note("en-exact", "p1-0", "p1-0", "network secure against", side="en", style="underline", color="green"),  # 跨 se-/cure
        note("item", "p1-1", "p1-1#1", "简短总结", color="blue"),
        note("cross", "p1-2", "p1-2", "接到下一页", color="pink"),
        note("cross2", "p1-2", "p1-2", "第二句", side="zh"),  # 跨页段落里只在第 2 页的那句
        note("no-sents", "p2-0", "p2-0", "整段", color="green"),
        note("edited", "p2-1", "p2-1", "我改的第二句"),
        note("partial", "p2-2", "p2-2", "一部分"),
        note("rotated", "p3-0", "p3-0", "highlights aligned", side="en", kind="question", body="Why rotate?", color="pink"),
        note("missing", "p1-0", "p1-0", "这句话不在任何地方"),
        note("gone", "p1-0", "p1-0", "稳健", deleted=True),
        note("plain-note", "p1-0", "p1-0", "", kind="note", body="no quote"),
    ]


def write_reader(root: Path, notes: list[dict], edits: dict | None = None):
    edits = edits if edits is not None else {"p2-1": {"zh": "改过的第一句。我改的第二句。", "base": "", "at": "2026-10-06T09:00:00+08:00"}}
    reader = {"schema": 1, "rev": 1, "edits": edits, "notes": {n["id"]: n for n in notes}, "paper_note": {}, "progress": {}}
    (root / "reader.json").write_text(json.dumps(reader, ensure_ascii=False), encoding="utf-8")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def text_under(pdf_bytes: bytes, page_no: int, quads: list[list[float]]) -> str:
    """PDFium 紧字框（PDF 用户空间）中心落在 quad 外接框里的字，按原顺序接起来。"""
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        with closing(doc[page_no - 1]) as page, closing(page.get_textpage()) as tp:
            out = []
            for q in quads:
                xs, ys = q[0::2], q[1::2]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                for i in range(tp.count_chars()):
                    l, b, r, t = tp.get_charbox(i)
                    cx, cy = (l + r) / 2, (b + t) / 2
                    if x0 <= cx <= x1 and y0 <= cy <= y1:
                        out.append(tp.get_text_range(i, 1))
            return "".join(out)
    finally:
        doc.close()


class PdfAnnotateBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "paper"
        build_paper(cls.root)
        cls.sha = hashlib.sha256((cls.root / "source.pdf").read_bytes()).hexdigest()
        cls.data, cls.stats = pa.export(cls.root)
        cls.items = {it["id"]: it for it in cls.stats["items"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def recovered(self, nid: str) -> str:
        it = self.items[nid]
        return "".join(text_under(self.data, int(pn), quads) for pn, quads in sorted(it["quads"].items(), key=lambda kv: int(kv[0])))


class TargetTest(PdfAnnotateBase):
    def assert_marks(self, nid, expected_en):
        self.assertIn(nid, self.items, self.stats["skipped"])
        self.assertEqual(norm(self.items[nid]["expected"]), norm(expected_en))
        self.assertEqual(norm(self.recovered(nid)), norm(expected_en))

    def test_zh_side_marks_whole_sentence(self):
        self.assert_marks("zh-sent", A_EN[1])
        self.assertEqual(self.items["zh-sent"]["mode"], "sentence")

    def test_en_side_exact_across_hyphen_break(self):
        self.assert_marks("en-exact", "network secure against")
        self.assertEqual(self.items["en-exact"]["mode"], "exact")

    def test_list_item_sentence(self):
        self.assert_marks("item", ITEM1_EN[1])

    def test_cross_page_paragraph(self):
        self.assert_marks("cross", X_EN[0])
        self.assertEqual(self.items["cross"]["pages"], [1, 2])
        got = norm(self.recovered("cross"))
        for junk in ("fixture", "figure", "sidebar", "scenarios"):  # 页眉、题注、边栏都不算进去
            self.assertNotIn(junk, got)
        self.assert_marks("cross2", X_EN[1])

    def test_no_sents_marks_whole_paragraph(self):
        self.assert_marks("no-sents", U_EN)
        self.assertEqual(self.items["no-sents"]["mode"], "para")

    def test_edited_paragraph_falls_back_to_whole(self):
        self.assert_marks("edited", E_EN)
        self.assertEqual(self.items["edited"]["mode"], "para")

    def test_unprinted_tail_does_not_grab_neighbouring_text(self):
        """段尾在原页上找不到时按长度估范围；逐字对齐不能把后面无关文字里巧合的字母（the、a bend）也标进去。"""
        self.assertEqual(norm(self.recovered("partial")), norm(P_PRINTED))

    def test_rotated_page(self):
        self.assert_marks("rotated", "highlights aligned")

    def test_missing_quote_is_counted(self):
        self.assertEqual(self.stats["total"], 10)  # 删掉的和没有引文的笔记不算
        self.assertEqual(self.stats["written"], 9)
        self.assertEqual([s["id"] for s in self.stats["skipped"]], ["missing"])
        s = self.stats["skipped"][0]
        self.assertEqual(s["page"], 1)
        self.assertEqual(s["quote"], "这句话不在任何地方")
        self.assertEqual(s["reason"], tr("引文在段落里找不到"))
        self.assertEqual(len(pa.skipped_lines(self.stats)), 1)

    def test_utf16_offsets(self):
        """译文里有补充平面字符时，句界要按 UTF-16 换算；按 Python 下标会把第 1 句也算进来。"""
        blocks = {"p1-0": json.loads((self.root / "paper.json").read_text())["blocks"][0]}
        t = pa.target_range(note("x", "p1-0", "p1-0", "稳健"), blocks, {})
        self.assertEqual(t["en"][t["start"]:t["end"]], A_EN[1])

    def test_align_rules_match_js(self):
        en, zh, s = aligned(["A b.", "C d."], ["甲。", "乙。"])
        self.assertIsNotNone(pa.align_of({"en": en, "zh": zh, "sents": s}))
        self.assertIsNone(pa.align_of({"en": en + "x", "zh": zh, "sents": s}))  # 总长对不上
        self.assertIsNone(pa.align_of({"en": en, "zh": zh, "sents": [[4, 2], [3, 4], s[-1]]}))  # 不递增
        self.assertIsNone(pa.align_of({"en": en, "zh": zh, "sents": [s[-1]]}))  # 少于两项


class AnnotationTest(PdfAnnotateBase):
    def annots(self):
        r = pypdf.PdfReader(io.BytesIO(self.data))
        out = []
        for i, p in enumerate(r.pages):
            for a in p.get("/Annots") or []:
                a = a.get_object()
                if a.get("/T") == "EasyRead":
                    out.append((i + 1, p, a))
        return r, out

    def by_id(self):
        return {str(a["/NM"]).removeprefix("easyread-"): (pn, p, a) for pn, p, a in self.annots()[1]}

    def test_subtypes_colors_contents(self):
        ann = self.by_id()
        self.assertEqual(ann["zh-sent"][2]["/Subtype"], "/Highlight")
        self.assertEqual(ann["en-exact"][2]["/Subtype"], "/Underline")
        self.assertEqual([round(float(v) * 255) for v in ann["en-exact"][2]["/C"]], list(pa.COLORS["green"]))
        self.assertEqual([round(float(v) * 255) for v in ann["item"][2]["/C"]], list(pa.COLORS["blue"]))
        self.assertEqual(ann["rotated"][2]["/Contents"], "Why rotate?")
        self.assertNotIn("/Contents", ann["zh-sent"][2])
        for _, _, a in ann.values():
            self.assertEqual(int(a["/F"]), 4)
            self.assertTrue(str(a["/M"]).startswith("D:20261006100000"))

    def test_appearance_streams(self):
        for pn, page, a in self.annots()[1]:
            ap = a["/AP"]["/N"].get_object()
            self.assertEqual(ap["/Subtype"], "/Form")
            data = ap.get_data().decode()
            if a["/Subtype"] == "/Highlight":
                self.assertEqual(ap["/Resources"]["/ExtGState"]["/GS0"]["/BM"], "/Multiply")
                self.assertIn(" f", data)
            else:
                self.assertIn(" S", data)

    def test_quads_inside_page(self):
        ann = self.annots()[1]
        self.assertEqual(len(ann), 10)  # 9 条，跨页那条两页各一个
        for pn, page, a in ann:
            box = page.cropbox
            q = [float(v) for v in a["/QuadPoints"]]
            self.assertEqual(len(q) % 8, 0)
            for k in range(0, len(q), 2):
                self.assertTrue(float(box.left) <= q[k] <= float(box.right) and float(box.bottom) <= q[k + 1] <= float(box.top), (pn, q))

    def test_keeps_links_outline_and_source(self):
        r = self.annots()[0]
        src = pypdf.PdfReader(str(self.root / "source.pdf"))
        links = lambda rd: sum(1 for p in rd.pages for a in (p.get("/Annots") or []) if a.get_object()["/Subtype"] == "/Link")
        self.assertEqual(links(r), links(src))
        self.assertEqual(links(r), 1)
        self.assertEqual([o.title for o in r.outline], [o.title for o in src.outline])
        self.assertEqual(len(r.outline), 2)
        self.assertEqual(hashlib.sha256((self.root / "source.pdf").read_bytes()).hexdigest(), self.sha)

    def test_renders_highlight(self):
        """PDFium 渲染时画出了注解（看高亮那一行有没有带颜色的像素）。"""
        doc = pdfium.PdfDocument(self.data)
        try:
            with closing(doc[1]) as page:
                img = page.render(scale=1, draw_annots=True).to_pil().convert("RGB")
                plain = page.render(scale=1, draw_annots=False).to_pil().convert("RGB")
        finally:
            doc.close()
        self.assertNotEqual(img.tobytes(), plain.tobytes())

    def test_filename(self):
        name = pa.filename(self.root)
        self.assertTrue(name.endswith(tr("-划线版") + ".pdf"))
        self.assertNotRegex(name, r'[\\/:*?"<>|]')


class NoNotesTest(unittest.TestCase):
    def test_no_highlights_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "p"
            build_paper(root)
            write_reader(root, [note("n", "p1-0", "p1-0", "", kind="note", body="x")])
            with self.assertRaises(pa.NoHighlights):
                pa.export(root)


class CliTest(PdfAnnotateBase):
    def run_cli(self, out, force=False):
        from easyread import cli
        from easyread.store import Workspace
        with patch.object(cli, "find", return_value=Workspace(self.root)):
            cli.cmd_export_pdf(argparse.Namespace(id="x", out=str(out) if out else None, force=force))

    def test_refuses_source_pdf(self):
        with self.assertRaises(SystemExit):
            self.run_cli(self.root / "source.pdf")
        with self.assertRaises(SystemExit):
            self.run_cli(self.root / "source.pdf", force=True)
        self.assertEqual(hashlib.sha256((self.root / "source.pdf").read_bytes()).hexdigest(), self.sha)

    def test_writes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_cli(Path(d))
            files = list(Path(d).iterdir())
            self.assertEqual([f.name for f in files], [pa.filename(self.root)])
            pypdf.PdfReader(str(files[0]))
            with self.assertRaises(SystemExit):
                self.run_cli(files[0])
            self.run_cli(files[0], force=True)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from easyread import launch, server
        from tests.test_hostcheck import MINI_PDF
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": cls.tmp.name})
        cls.env.start()
        cls.cfg = patch.object(server.config, "CONFIG_PATH", Path(cls.tmp.name) / "no-config.json")
        cls.cfg.start()
        cls.app = server.App(server.config.load())
        server.Handler.app = cls.app
        cls.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        ws, _ = cls.app.lib.create_from_pdf(MINI_PDF, "x.pdf")
        cls.ws = ws
        build_paper(ws.root)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.cfg.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def post(self, host=None, headers=None):
        from tests.test_hostcheck import raw
        return raw(self.port, "POST", f"/api/p/{self.ws.id}/annotated-pdf", host or f"127.0.0.1:{self.port}",
                   headers=headers if headers is not None else {"X-Token": self.app.token, "Content-Type": "application/json"}, body=b"{}")

    def listing(self):
        return sorted(str(p.relative_to(self.tmp.name)) for p in Path(self.tmp.name).rglob("*") if "history" not in p.parts)

    def test_download(self):
        before = self.listing()
        sha = hashlib.sha256((self.ws.root / "source.pdf").read_bytes()).hexdigest()
        status, head, body = self.post()
        self.assertEqual(status, 200, body[:300])
        self.assertIn("Content-Type: application/pdf", head)
        self.assertIn("Cache-Control: no-store", head)
        self.assertIn("X-Content-Type-Options: nosniff", head)
        self.assertRegex(head, r"Content-Disposition: attachment; filename=\"annotated\.pdf\"; filename\*=UTF-8''[^\r\n]+")
        self.assertIn("X-EasyRead-Skipped: 1", head)
        self.assertIn("X-EasyRead-Written: 9", head)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(len(pypdf.PdfReader(io.BytesIO(body)).pages), 3)
        self.assertEqual(self.listing(), before)  # 没往文献库写任何文件
        self.assertEqual(hashlib.sha256((self.ws.root / "source.pdf").read_bytes()).hexdigest(), sha)

    def test_needs_token_host_origin(self):
        status, _, _ = self.post(headers={})
        self.assertEqual(status, 403)
        status, _, _ = self.post(headers={"X-Token": "wrong"})
        self.assertEqual(status, 403)
        status, _, _ = self.post(host="evil.example:80")
        self.assertEqual(status, 403)
        status, _, _ = self.post(headers={"X-Token": self.app.token, "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_no_highlights_400(self):
        reader = (self.ws.root / "reader.json").read_bytes()
        try:
            write_reader(self.ws.root, [])
            status, _, body = self.post()
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"], tr("这篇还没有划线"))
        finally:
            (self.ws.root / "reader.json").write_bytes(reader)


if __name__ == "__main__":
    unittest.main()
