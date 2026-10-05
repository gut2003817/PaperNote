"""漏段检测：extract 里有整段正文没进任何块时能报出来，且不误报。不调模型。  python -m unittest tests.test_coverage"""
import shutil
import tempfile
import unittest
from pathlib import Path

from easyread import coverage
from easyread.store import Workspace, write_json_atomic

HEADER = "IEEE Communications Magazine • October 2025 111"
P_A = ("The proposed framework collects threat information from the simulator and passes it to the language model, "
       "which analyses the records and generates matching security strategies in real time. It then feeds them back.")
P_MISSING = ("For the space-based network, we construct the satel\x02lite system including GEO and LEO satellites, and develop a "
             "physical layer protocol. For the air-based network, we deploy UAVs equipped with WLAN protocols and configure "
             "the random walk mobility pattern to enhance network dynamics.")
P_B = ("Experiments on three datasets validate the performance of the framework against unknown threats and demonstrate "
       "its potential to address diverse security challenges.")


def wrap(text: str, width: int = 48) -> str:
    """像 PDF 抽字那样按固定宽度折行（在空格处断，也能在连字号处断）。"""
    lines, cur = [], ""
    for w in text.split(" "):
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return "\n".join(lines + [cur])


def block(i, page, en, **kw):
    return {"id": f"b{i}", "type": kw.pop("type", "para"), "page": page, "en": en, "zh": "译文", **kw}


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="easyread-cov-"))
        (self.root / "extract").mkdir()
        self.addCleanup(shutil.rmtree, self.root, True)

    def ws(self, pages: dict, blocks: list, meta=None, references=None, done=None):
        for n, text in pages.items():
            (self.root / "extract" / f"page-{n:03d}.txt").write_text(text, encoding="utf-8")
        m = {"page_count": len(pages), "authors": "Ann Lee, Bob Roe", "affiliation": "Some University", "title_en": "A Study of Things"}
        m.update(meta or {})
        write_json_atomic(self.root / "paper.json", {"meta": m, "references": references or [], "blocks": blocks,
                                                     "translation": {"done_pages": done if done is not None else sorted(pages)}})
        return Workspace(self.root)

    def test_missing_paragraph_detected(self):
        ws = self.ws({1: f"{HEADER}\n{wrap(P_A)}\n{wrap(P_MISSING)}\n{wrap(P_B)}\n"},
                     [block(1, 1, P_A), block(2, 1, P_B)])
        gaps = coverage.find_gaps(ws)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["page"], 1)
        self.assertTrue(gaps[0]["text"].startswith("For the space-based network"))
        self.assertIn("satellite system", gaps[0]["text"])  # \x02 和断行连字号不留在显示文字里
        self.assertGreater(gaps[0]["chars"], 250)

    def test_all_covered_no_gap(self):
        ws = self.ws({1: f"{HEADER}\n{wrap(P_A)}\n{wrap(P_MISSING)}\n{wrap(P_B)}\n"},
                     [block(1, 1, P_A), block(2, 1, P_MISSING.replace("\x02", "")), block(3, 1, P_B)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_hyphenation_and_control_chars_do_not_break_matching(self):
        # 块里是完整单词 satellite；extract 里是 satel-\nlite 或 satel\x02lite
        text = "The satellite system including GEO and LEO satellites is built over a physical layer protocol that is simple.\n"
        broken = text.replace("satellite system", "satel-\nlite system", 1).replace("satellites is", "satel\x02lites is")
        ws = self.ws({1: broken + wrap(P_B)}, [block(1, 1, text.strip()), block(2, 1, P_B)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_header_footer_and_page_numbers_ignored(self):
        page = (f"{HEADER}\n{wrap(P_A)}\n112\nAuthorized licensed use limited to: Some University. Downloaded on September 21,2026 "
                f"at 05:53:46 UTC from IEEE Xplore. Restrictions apply. \n")
        ws = self.ws({1: page}, [block(1, 1, P_A)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_references_and_later_pages_ignored(self):
        refs = ["Y. Wang et al., Six-Trust for 6G: Toward a Secure and Trustworthy Future Network, IEEE Access, vol. 11, 2023."]
        tail = "References\n[1] " + refs[0] + "\n[2] Some other entry that is not in the list anywhere at all, 2024, pp. 1-9.\n"
        bio = "Biographies\nAnn Lee is a professor who has published many papers in many venues over a long career.\n"
        ws = self.ws({1: wrap(P_A) + "\n" + tail, 2: bio}, [block(1, 1, P_A)], references=[{"id": "1", "text": refs[0]}])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_figure_text_and_caption_not_reported(self):
        cap = "FIGURE 2. Illustration of the proposed framework and the simulator that collects threat information."
        labels = "\n".join(["The Self-Evolving", "Security Framework", "LLM-6GNG", "Integrated Strategy", "6G-INST",
                            "Instruction and Strategy", "Twin Specific Agent", "Step 1. Collect data", "Threat Information", "Feedback Loop"])
        page = f"{wrap(P_A)}\n{wrap(cap, 60)}\n{labels}\n"
        ws = self.ws({2: page, 1: "x"}, [block(1, 2, P_A), {"id": "fig2", "type": "figure", "page": 2, "caption_en": cap, "image_en": ""}],
                     done=[2])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_missing_body_on_figure_page_still_reported(self):
        page = f"{wrap(P_A)}\n{wrap(P_MISSING)}\nLLM-6GNG\n"
        ws = self.ws({1: page}, [block(1, 1, P_A), {"id": "fig1", "type": "figure", "page": 1, "caption_en": "FIGURE 1. x", "image_en": ""}])
        self.assertEqual(len(coverage.find_gaps(ws)), 1)

    def test_list_items_and_bullets_covered(self):
        page = "• We present the LLM-based network guard, a novel method that applies multi-agent reasoning.\n• A simulator is built on top of two tools.\n"
        lst = {"id": "l1", "type": "list", "page": 1, "items": [{"en": "We present the LLM-based network guard, a novel method that applies multi-agent reasoning.", "zh": "译"},
                                                                {"en": "A simulator is built on top of two tools.", "zh": "译"}]}
        self.assertEqual(coverage.find_gaps(self.ws({1: page}, [lst])), [])

    def test_first_page_author_footnotes_ignored(self):
        page = (f"{wrap(P_A)}\nAnn Lee and Bob Roe are with Some University, China; Carl Poe is with Another Institute of Technology, Korea.\n"
                "Ann Lee, Bob Roe\n")
        ws = self.ws({1: page}, [block(1, 1, P_A)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_short_gap_below_threshold_ignored(self):
        ws = self.ws({1: wrap(P_A) + "\nA short stray sentence here.\n"}, [block(1, 1, P_A)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_no_extract_or_no_blocks_is_silent(self):
        ws = self.ws({}, [block(1, 1, P_A)], meta={"page_count": 3})  # 有块没 extract
        self.assertEqual(coverage.find_gaps(ws), [])
        ws = self.ws({1: wrap(P_MISSING)}, [])  # 有 extract 没块（还没译）
        self.assertEqual(coverage.find_gaps(ws), [])
        self.assertEqual(coverage.find_gaps(Workspace(self.root / "nope")), [])  # 论文夹都不存在

    def test_untouched_pages_not_reported_when_partially_translated(self):
        ws = self.ws({1: wrap(P_A), 2: wrap(P_MISSING)}, [block(1, 1, P_A)], done=[1])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_cross_page_paragraph_absorbed_by_previous_block(self):
        # 段落从第 1 页末尾接到第 2 页开头，译文把整段收进第 1 页的块
        first, rest = P_A[:100], P_A[100:]
        ws = self.ws({1: wrap(first), 2: wrap(rest) + "\n" + wrap(P_B)}, [block(1, 1, P_A), block(2, 2, P_B)])
        self.assertEqual(coverage.find_gaps(ws), [])

    def test_missing_text_after_cross_page_start_reported_from_sentence_start(self):
        # 上一页的块收到 “…network. For” 之前，下一句整段没块
        ws = self.ws({1: wrap(P_A), 2: wrap(P_A[-30:] + " " + P_MISSING)}, [block(1, 1, P_A)])
        gaps = coverage.find_gaps(ws)
        self.assertEqual([g["page"] for g in gaps], [2])

    def test_report_lines(self):
        gaps = [{"page": 3, "chars": 464, "text": "For the space-based network " + "x" * 100}]
        lines = coverage.report_lines("abc", gaps)
        self.assertIn("3", lines[1])  # 文字随界面语言变，只核数字
        self.assertIn("464", lines[1])
        self.assertIn("--pages 2,3", lines[2])
        self.assertEqual(len(coverage.report_lines("abc", [])), 1)


class JobLogHintTest(unittest.TestCase):
    """译完后 job.log 里多一行漏段提示；纯本地比对，引擎是假的。"""

    def run_translate(self, extract_text: str) -> str:
        import threading
        from unittest import mock

        from easyread import engines, translate
        from tests.test_translate import fake_engine, make_ws
        ws = make_ws(1)
        self.addCleanup(shutil.rmtree, ws.root, True)
        (ws.root / "extract" / "page-001.txt").write_text(extract_text, encoding="utf-8")
        with mock.patch.object(engines, "run", fake_engine(set(), [])), mock.patch.object(translate.pdfwork, "locate", lambda r: None), \
                mock.patch.object(translate, "tex_problems", lambda t: []):
            translate.translate_pages(ws, {"engine": "openai", "batch_pages": 1, "concurrency": 1, "openai": {"vision": False}}, [1], threading.Event(), lambda *a: None)
        return (ws.root / "job.log").read_text(encoding="utf-8")

    def test_gap_warning_written(self):
        self.assertIn("easyread check", self.run_translate(wrap(P_MISSING)))

    def test_no_warning_when_clean(self):
        self.assertNotIn("easyread check", self.run_translate("Text of page 1."))


if __name__ == "__main__":
    unittest.main()
