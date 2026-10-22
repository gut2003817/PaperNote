"""原页定位：跨页段落、段尾太短时，框要落在段落本身所在的栏，而不是被估算长度撑到别处。

测试 PDF 在这里手写（纯 ASCII PDF 语法、Helvetica），走真实的抽字（pdfium）与 locate 管线。
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from easyread.pdf import pdfwork
from easyread.library.store import write_json_atomic

W, H = 612, 792
LEFT, RIGHT = 54, 324  # 两栏左边界（pt）；栏宽约 234pt，Helvetica 9pt 每行约 48 字


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines(text, x, y, width=48):
    """一段文字按栏宽折行，每行一个 Td，从 (x, y) 往下排。"""
    out = []
    for i, line in enumerate(textwrap.wrap(text, width)):
        out.append(f"BT /F1 9 Tf {x} {y - i * 11} Td ({_esc(line)}) Tj ET")
    return out, y - len(textwrap.wrap(text, width)) * 11


def make_pdf(path, pages):
    """pages: 每页一串内容流指令（按字串顺序就是 PDF 内容流 = 抽出来的字元流顺序）。"""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for ops in pages:
        stream = "\n".join(ops).encode("ascii")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('ascii')}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("ascii")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii")
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode("ascii")
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    Path(path).write_bytes(bytes(out))


AUTHORS = ("Alice Quinn Example, Bob Rivers Sample, Carol Stone Model, Dave Turner Fixture, "
           "Erin Upton Mock, Frank Vance Stub, Grace Wells Dummy, Henry Xu Placeholder")
INTRO = ("The left column opens the introduction with a paragraph that is long enough to fill "
         "several lines of text and then ends cleanly before the right column begins.")
CROSS_P1 = ("Toward resilient frameworks, numerous studies have been conducted to address emerging "
            "problems in layered networks, including intrusion detection, trust management and "
            "lightweight cryptography for constrained devices on the bottom of the right column")
CROSS_P2 = ("which continues on the following page with further discussion of anomaly detection, "
            "explainable models and adaptive policies that close the paragraph against unknown threats.")
SHORT_TAIL = ("As usual the left column opens the introduction with a paragraph long enough to fill "
              "several lines of text and then closes with k as m.")
NEXT = "A later paragraph on the second page starts here and has nothing to do with the authors."


def build(root: Path, intro=INTRO):
    """第 1 页：左栏 INTRO、右栏 CROSS 的前半（段尾在第 2 页）；作者名单画在页首、但在内容流的最后
    （IEEE 双栏论文抽出来就是这个顺序）。第 2 页：左栏先是 CROSS 的后半，再接 NEXT。"""
    left, _ = _lines(intro, LEFT, 600)
    right, _ = _lines(CROSS_P1, RIGHT, 300)
    authors, _ = _lines(AUTHORS, LEFT, 740, width=110)
    p2a, y = _lines(CROSS_P2, LEFT, 740)
    p2b, _ = _lines(NEXT, LEFT, y - 20)
    make_pdf(root / "source.pdf", [left + right + authors, p2a + p2b])
    pdfwork.extract_text(root / "source.pdf", root / "extract")


class CrossPageLocateTest(unittest.TestCase):
    def locate(self, blocks, intro=INTRO):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        build(root, intro)
        write_json_atomic(root / "paper.json", {"blocks": blocks})
        return root, pdfwork.locate(root)

    def test_cross_page_paragraph_stays_in_its_right_column_slot(self):
        root, layout = self.locate([
            {"id": "intro", "page": 1, "type": "para", "en": INTRO},
            {"id": "cross", "page": 1, "type": "para", "en": CROSS_P1 + " " + CROSS_P2},
            {"id": "next", "page": 2, "type": "para", "en": NEXT},
        ])
        cross = layout["cross"]
        self.assertEqual(cross["page"], 1)
        self.assertEqual(cross["src"], "text")
        x0, y0, x1, y1 = cross["box"]
        self.assertGreater(x0, 0.5)  # 右栏
        self.assertNotIn("boxes", cross)  # 没有吃进左栏或页首作者名单
        # 第 1 页 CROSS 从 y=300pt 起往下排：框的上沿在那附近，不在页首作者名单（y=740pt）那里。
        self.assertAlmostEqual(y0, (H - 300 - 9) / H, delta=0.02)
        self.assertGreater(y1, y0 + 0.04)  # 右栏那几行都框进去了
        self.assertLess(y1, 0.75)
        self.assertEqual(layout["intro"]["src"], "text")
        self.assertLess(layout["intro"]["box"][2], 0.5)
        self.assertEqual(layout["next"]["src"], "text")
        self.assertEqual((root / "extract/locate.version").read_text(encoding="utf-8"), pdfwork.LOCATE_VERSION)

    def test_short_tail_found_early_does_not_cut_the_paragraph(self):
        # 最后一段纯文字只剩 " as "（夹在两个公式之间）：旧做法在段首 "As usual" 就找到段尾，框只剩一点点。
        en = SHORT_TAIL.replace("with k as m.", "with $k$ as $m$.")
        _, layout = self.locate([{"id": "intro", "page": 1, "type": "para", "en": en}], intro=SHORT_TAIL)
        x0, y0, x1, y1 = layout["intro"]["box"]
        lines = len(textwrap.wrap(SHORT_TAIL, 48))
        self.assertEqual(layout["intro"]["src"], "text")
        self.assertGreater(y1 - y0, (lines - 1) * 11 / H)  # 整段几行都在框里
        self.assertLess(x1, 0.5)  # 没有对到右栏去

    def test_text_that_differs_at_the_end_does_not_jump_to_the_next_column(self):
        # 译文英文末尾多出 PDF 上没有的字：最后不足一小段的字母不能在右栏巧合对上。
        en = INTRO + " Let it be."
        _, layout = self.locate([{"id": "intro", "page": 1, "type": "para", "en": en}])
        self.assertLess(layout["intro"]["box"][2], 0.5)
        self.assertGreater(layout["intro"]["box"][3] - layout["intro"]["box"][1], 2 * 11 / H)

    def test_old_layout_version_is_recomputed(self):
        root, _ = self.locate([{"id": "intro", "page": 1, "type": "para", "en": INTRO}])
        write_json_atomic(root / "layout.json", {"stale": {"page": 1, "box": [0, 0, 1, 1], "src": "head"}})
        (root / "extract/locate.version").write_text("5", encoding="utf-8")
        pdfwork.refresh_layout(root)
        self.assertNotIn("stale", (root / "layout.json").read_text(encoding="utf-8"))
        self.assertEqual((root / "extract/locate.version").read_text(encoding="utf-8"), pdfwork.LOCATE_VERSION)


if __name__ == "__main__":
    unittest.main()
