"""译文语言：中文提示词不变、其他语言换掉中文专属的规则、第一次翻译时记下语言、旧论文按中文。  python -m unittest tests.translate.test_langs"""
import json
import shutil
import threading
import unittest
from unittest import mock

from easyread.engines import engines
from easyread.translate import langs, prompts, prompts_en, terms, translate
from easyread.server import settings_api
from easyread.library.store import write_json_atomic
from tests.translate.test_translate import make_ws


def set_meta(ws, **kw):
    paper = ws.load("paper")
    paper["meta"].update(kw)
    write_json_atomic(ws.root / "paper.json", paper)


class LangsTest(unittest.TestCase):
    def setUp(self):
        self.ws = make_ws(2)

    def tearDown(self):
        shutil.rmtree(self.ws.root, ignore_errors=True)

    def test_chinese_prompt_unchanged(self):
        self.assertIs(prompts.rules("zh"), prompts.RULES)
        self.assertIs(prompts.schema("zh"), prompts.SCHEMA)
        with mock.patch.object(langs, "of_paper", lambda meta, cfg=None: "zh"):
            text = prompts.translate(self.ws, [1], "text", "")
        self.assertIn("译成中文，这次只处理第 1 页", text)
        self.assertIn("standard error 译“标准误差”", text)

    def test_every_swap_applies(self):
        for old, _ in prompts._RULES_SWAP:
            self.assertIn(old, prompts.RULES)
        for old, _ in prompts._SCHEMA_SWAP:
            self.assertIn(old, prompts.SCHEMA)

    def test_other_language_prompt(self):
        set_meta(self.ws, target="ja")
        for text in (prompts.translate(self.ws, [1], "text", ""),
                     prompts_en.fill(self.ws, [1], {"p1-1": "Hello"})):
            self.assertIn("日语", text)
            self.assertNotIn("标准误差", text)
            self.assertNotIn("中文译文", text)
            self.assertNotIn("中文语序", text)

    def test_traditional_chinese_keeps_chinese_rules(self):
        # 繁體版：上游的 zh-Hant 当 zh-TW 的别名，走台湾用语的提示词
        set_meta(self.ws, target="zh-Hant")
        text = prompts.translate(self.ws, [1], "text", "")
        self.assertIn("译成繁體中文（台灣用語）", text)
        self.assertIn("中文语序", text)  # 中文规则照旧，只多一条繁体用字要求
        self.assertIn("台灣慣用詞", text)
        self.assertIn("不超过 12 字", prompts_en.fill(self.ws, [1], {"p1-1": "Hello"}))
        self.assertNotIn("台灣慣用詞", prompts.rules("zh"))

    def test_italian_prompt(self):
        set_meta(self.ws, target="it")
        text = prompts.translate(self.ws, [1], "text", "")
        self.assertIn("意大利语（Italiano）", text)
        self.assertNotIn("标准误差", text)

    def test_english_prompt_any_source_language(self):
        """#48 译成英文：原文可能是德语、中文等任何语言；原文本来就是英文时照抄。"""
        set_meta(self.ws, target="en")
        texts = (prompts.translate(self.ws, [1], "text", ""), prompts_en.fill(self.ws, [1], {"p1-1": "Hallo"}),
                 prompts.rules("en"))  # 重译一段也用 rules
        for text in texts:
            self.assertIn("英文（English）", text)
            self.assertIn("原文不一定是英文", text)
            self.assertIn("照抄原文", text)
            self.assertNotIn("标准误差", text)
            self.assertNotIn("中文语序", text)
        self.assertIn("English term (原文术语)", texts[0])
        self.assertIn('{"en": "原文术语", "zh": "English term"}', texts[0])
        self.assertIn('{"en": "原文术语", "zh": "English term"}', texts[1])
        self.assertIn("不超过 6 个词", texts[1])
        self.assertNotIn("原文不一定是英文", prompts.rules("de"))  # 只加在英语上
        self.assertIn("原文术语", prompts.consistency([], {}, "英文（English）"))

    def test_english_target_end_to_end(self):
        """德语原文译成英文：en 存原文、zh 存英文译文，记下 target=en；问 AI 用英文回答。"""
        def run(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            self.assertIn("译成英文（English）", prompt)
            return json.dumps({"meta": {"title_zh": "Attention is all you need", "title_en": "Aufmerksamkeit ist alles"},
                               "blocks": [{"id": "p1-1", "type": "para", "page": 1, "en": "Das ist gut. ‖ Sehr gut.", "zh": "That is good. ‖ Very good."}]})
        cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 1, "openai": {"vision": False}, "target": "en"}
        with mock.patch.object(engines, "run", run), mock.patch.object(translate.netcheck, "problem", lambda cfg: ""), \
                mock.patch.object(translate.pdfwork, "locate", lambda root: None), mock.patch.object(translate, "tex_problems", lambda tex: []):
            translate.translate_pages(self.ws, cfg, [1], threading.Event(), lambda *a: None)
        paper = self.ws.load("paper")
        self.assertEqual(paper["meta"]["target"], "en")
        b = next(b for b in paper["blocks"] if b["id"] == "p1-1")
        self.assertEqual((b["en"], b["zh"]), ("Das ist gut. Sehr gut.", "That is good. Very good."))
        self.assertTrue(b.get("sents"))  # 句子对齐照常
        self.assertEqual(langs.reply_lang(paper["meta"]), "英文（English）")

    def test_cjk_source_terms_unify(self):
        """原文是中文、译成英文：术语按字串数次数（中文词间没空格），后来的说法换成术语表里的。"""
        self.assertEqual(terms.mentions_count("我们用标准误差。标准误差很小", "标准误差"), 2)
        data = {"glossary": [{"en": "标准误差", "zh": "std error"}],
                "blocks": [{"id": "p1-1", "type": "para", "en": "标准误差很大。", "zh": "The std error is large."}]}
        terms.unify([{"en": "标准误差", "zh": "standard error"}], data)
        self.assertEqual(data["blocks"][0]["zh"], "The standard error is large.")

    def test_old_papers_count_as_chinese(self):
        self.assertEqual(langs.of_paper({"title_zh": "旧论文"}, {"target": "ja"}), "zh")
        self.assertEqual(langs.of_paper({}, {"target": "ja"}), "ja")
        self.assertEqual(langs.of_paper({"target": "fr"}, {"target": "ja"}), "fr")
        self.assertEqual(langs.of_paper({}, {"target": "xx"}), "zh")

    def test_reply_language(self):
        self.assertEqual(langs.reply_lang({"target": "de"}), "德语（Deutsch）")
        self.assertEqual(langs.reply_lang({"title_zh": "旧论文"}), "中文")
        with mock.patch("easyread.app.i18n.lang", lambda: "en"):
            self.assertEqual(langs.reply_lang({}), "英文（English）")

    def test_first_translation_records_target(self):
        def run(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            self.assertIn("译成韩语", prompt)
            return json.dumps({"blocks": [{"id": "p1-1", "type": "para", "page": 1, "en": "x", "zh": "번역"}]})
        cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 1, "openai": {"vision": False}, "target": "ko"}
        with mock.patch.object(engines, "run", run), mock.patch.object(translate.netcheck, "problem", lambda cfg: ""), \
                mock.patch.object(translate.pdfwork, "locate", lambda root: None), mock.patch.object(translate, "tex_problems", lambda tex: []):
            translate.translate_pages(self.ws, cfg, [1], threading.Event(), lambda *a: None)
            self.assertEqual(self.ws.load("paper")["meta"]["target"], "ko")
            cfg["target"] = "ja"  # 之后改设置，这篇不跟着变
            translate.translate_pages(self.ws, cfg, [1], threading.Event(), lambda *a: None)
        self.assertEqual(self.ws.load("paper")["meta"]["target"], "ko")

    def test_import_remembers_target(self):
        langs.remember(self.ws, "fr")
        self.assertEqual(self.ws.load("paper")["meta"]["target"], "fr")
        langs.remember(self.ws, "de")  # 已经记过的不改
        self.assertEqual(self.ws.load("paper")["meta"]["target"], "fr")
        other = make_ws(1)
        paper = other.load("paper")
        paper["blocks"] = [{"id": "p1-1", "type": "para", "page": 1, "en": "x", "zh": "旧译文"}]
        write_json_atomic(other.root / "paper.json", paper)
        langs.remember(other, "ja")  # 已经有中文译文的旧论文不改
        langs.remember(self.ws, "xx")
        self.assertNotIn("target", other.load("paper")["meta"])
        shutil.rmtree(other.root, ignore_errors=True)

    def test_settings_rejects_unknown_target(self):
        with mock.patch.object(settings_api.config, "save", lambda patch: patch), mock.patch.object(settings_api.config, "public", lambda c: c):
            self.assertEqual(settings_api.save_config({"target": "xx"})["config"]["target"], "zh")
            self.assertEqual(settings_api.save_config({"target": "es"})["config"]["target"], "es")
            for code in ("zh-TW", "it", "en"):
                self.assertEqual(settings_api.save_config({"target": code})["config"]["target"], code)
            self.assertEqual(settings_api.save_config({"target": "zh-Hant"})["config"]["target"], "zh-TW")  # 上游代码当别名


if __name__ == "__main__":
    unittest.main()
