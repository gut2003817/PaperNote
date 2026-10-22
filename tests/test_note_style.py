"""笔记帮手的繁体写作习惯：只在回答语言是繁体中文时加进点评／帮我改／起草稿的提示词，翻译、问 AI 不受影响。  python -m unittest tests.test_note_style"""
import shutil
import unittest
from unittest import mock

from easyread.chat import answer_styles
from easyread.chat import chat
from easyread.translate import langs
from easyread.chat import notehelp
from easyread.translate import prompts
from easyread.library.store import write_json_atomic
from tests.translate.test_translate import make_ws

MARK = "寫筆記的文字習慣"  # i18n-ok 提示词
MODES = ("review", "revise", "draft")
# 常见的简体专有字（繁体写法不同）；规则文字里一个都不该出现
SIMPLIFIED = set("这个们说对为与来时问还会应开关发实现经过种体术译软网络数据库设置务层认读写变从")


def make(target):
    ws = make_ws(2)
    paper = ws.load("paper")
    paper["meta"].update(target=target, title_en="T", title_zh="題")
    write_json_atomic(ws.root / "paper.json", paper)
    return ws


class NoteStyleTest(unittest.TestCase):
    def tearDown(self):
        for ws in getattr(self, "wss", []):
            shutil.rmtree(ws.root, ignore_errors=True)

    def ws(self, target):
        w = make(target)
        self.wss = getattr(self, "wss", []) + [w]
        return w

    def test_traditional_has_rule_in_all_modes(self):
        ws = self.ws("zh-TW")
        for mode in MODES:
            for engine in ("claude", "openai"):
                text = notehelp.prompt(ws, mode, "我的筆記", engine)
                self.assertEqual(text.count(MARK), 1, (mode, engine))
                self.assertIn(langs.TW_STYLE, text)  # 原来的繁体要求还在
                self.assertLess(text.index(langs.TW_STYLE), text.index(MARK))
                self.assertLess(text.index(MARK), text.index(notehelp.ASK[mode]))  # 规则在任务描述之前

    def test_other_languages_have_no_rule(self):
        for target in ("zh", "en"):
            ws = self.ws(target)
            for mode in MODES:
                self.assertNotIn(MARK, notehelp.prompt(ws, mode, "my note", "claude"), (target, mode))
            self.assertEqual(langs.note_style({"target": target}), "")

    def test_untranslated_follows_ui_language(self):
        # 没翻过的论文：跟界面语言，和 reply_note 一致
        from easyread.app import i18n
        for ui, want in (("zh-TW", True), ("zh", False), ("en", False)):
            with mock.patch.object(i18n, "lang", lambda ui=ui: ui):
                self.assertEqual(bool(langs.note_style({})), want, ui)
                self.assertEqual(bool(langs.note_style({})), bool(langs.reply_note({})), ui)

    def test_rule_is_additive_only(self):
        ws = self.ws("zh-TW")
        for mode in MODES:
            with_rule = notehelp.prompt(ws, mode, "n", "claude")
            with mock.patch.object(langs, "note_style", lambda meta: ""):
                without = notehelp.prompt(ws, mode, "n", "claude")
            self.assertEqual(with_rule.replace(langs.NOTE_STYLE + "\n", ""), without)

    def test_translate_chat_answer_unaffected(self):
        for target in ("zh", "zh-TW", "en"):
            ws = self.ws(target)
            with mock.patch.object(langs, "of_paper", lambda meta, cfg=None, t=target: t):
                texts = [prompts.translate(ws, [1], "claude", "")]
            for style in (answer_styles.DEFAULT, answer_styles.STE100):
                texts.append(chat.prompt(ws, [{"role": "user", "content": "q"}], None, "", "claude", answer_style=style))
            texts.append(prompts.answer(ws, {"anchor": None, "body": "q"}))
            for t in texts:
                self.assertNotIn(MARK, t, target)
                self.assertNotIn("去 AI 腔", t, target)
            # 这几个入口压根不碰 note_style：把它换成会爆的函数也照常生成
            with mock.patch.object(langs, "note_style", side_effect=AssertionError("不该被调用")):
                chat.prompt(ws, [{"role": "user", "content": "q"}], None, "", "claude")
                prompts.answer(ws, {"anchor": None, "body": "q"})
                with mock.patch.object(langs, "of_paper", lambda meta, cfg=None, t=target: t):
                    prompts.translate(ws, [1], "claude", "")

    def test_protects_structure(self):
        for token in ("Markdown", "$TeX$", "程式碼", "[n]", "引文", "專有名詞", "照原樣"):  # i18n-ok 提示词
            self.assertIn(token, langs.NOTE_STYLE)

    def test_rule_has_no_simplified_chars(self):
        self.assertEqual(sorted(SIMPLIFIED & set(langs.NOTE_STYLE)), [])

    def test_rule_length(self):
        self.assertGreaterEqual(len(langs.NOTE_STYLE), 400)
        self.assertLessEqual(len(langs.NOTE_STYLE), 800)


if __name__ == "__main__":
    unittest.main()
