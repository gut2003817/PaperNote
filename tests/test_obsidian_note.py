"""Obsidian 笔记的提示词、回复容错与固定 Markdown 结构。"""
from __future__ import annotations

import copy
import json
import re
from datetime import date

import pytest

from easyread import langs, obsidian_note
from easyread.i18n import tr


@pytest.fixture
def ctx():
    return {"title": "論文標題", "authors": ["Alice", "Bob"], "year": "2026",
            "source": "https://example.test/paper", "text": "PAPER_TEXT_SENTINEL",
            "marks": [{"quote": "第一行\n第二行", "page": 3, "body": "待討論", "side": "zh"},
                      {"quote": "無頁碼", "page": None, "body": "", "side": "en"}],
            "figures": [{"id": "fig-a", "num": 2, "page": 4, "caption": "架構圖", "has_box": True},
                        {"id": "fig-b", "num": 3, "page": 5, "caption": "不可截圖", "has_box": False}]}


@pytest.fixture
def data():
    return {"hook": "一句話亮點。", "short": "6G-SAGIN", "tags": ["6G", "security"],
            "problem": "# 重複標題\n研究問題", "method": "方法說明", "result": "結果說明",
            "limits": "樣本有限", "figures": [{"id": "fig-a", "desc": "整體架構"}],
            "diagrams": [{"title": "方法流程", "mermaid": "graph TD\nA --> B"}]}


def test_render_has_single_h1_and_frontmatter_fields(ctx, data):
    text = obsidian_note.render(ctx, data, {}, today="2026-10-22")
    assert text.startswith("---\n")
    header = text.split("---\n")[1]
    for field in ("tags", "year", "authors", "source", "created"):
        assert f"{field}:" in header
    assert '  - "Alice"' in header and '  - "6G"' in header
    assert 'created: "2026-10-22"' in header
    assert re.findall(r"^# .*$", text, re.M) == ["# 論文標題"]
    assert "Alice" not in text.split("---\n", 2)[2]
    assert ctx["source"] not in text.split("---\n", 2)[2]


def test_render_section_order(ctx, data):
    text = obsidian_note.render(ctx, data, {"fig-a": "a.png"})
    sections = ["# 論文標題", "## 30 秒版", "## 問題與動機", "## 方法重點",
                "**方法流程**", "```mermaid", "## 結果", "## 重要圖表", "## 我的劃線",
                "## 限制與我的想法", "### 我的想法"]
    positions = [text.index(s) for s in sections]
    assert positions == sorted(positions)
    assert "> 第一行\n> 第二行\n（第 3 頁）\n筆記：待討論" in text
    assert "> 無頁碼\n\n" in text


def test_render_my_thoughts_is_empty(ctx, data):
    data["thoughts"] = "AI 不該寫的感想"
    text = obsidian_note.render(ctx, data, {})
    assert text.split("### 我的想法", 1)[1] == "\n\n"
    assert data["thoughts"] not in text


def test_render_empty_marks_and_figures_placeholders():
    text = obsidian_note.render({}, {}, {})
    assert "## 我的劃線\n\n（本篇沒有劃線）" in text
    assert "（論文沒有明確討論限制）" in text
    assert "重要圖表" not in text and "```mermaid" not in text
    assert "# 未命名論文" in text
    assert 'authors: []' in text and 'tags: []' in text
    assert f'created: "{date.today().isoformat()}"' in text
    assert "# SHORT" in obsidian_note.render({}, {"short": "SHORT"}, {})


def test_render_unknown_figure_id_is_dropped(ctx, data):
    data["figures"] = [{"id": "unknown", "desc": "壞圖"}, {"id": "fig-a", "desc": "缺檔"}]
    text = obsidian_note.render(ctx, data, {"unknown": "bad.png", "fig-b": "unselected.png"})
    assert "![" not in text and "重要圖表" not in text


def test_render_image_link_is_url_encoded(ctx, data):
    text = obsidian_note.render(ctx, data, {"fig-a": "paper name(#1).png"})
    assert "![圖2 整體架構](附圖/paper%20name%28%231%29.png)\n圖2：整體架構（第 4 頁）" in text


def test_render_yaml_escapes_quotes_and_newlines(ctx, data):
    value = 'A"B\\C\nD\rE'
    ctx.update(authors=[value], source=value, year=value)
    data["tags"] = [value]
    header = obsidian_note.render(ctx, data, {}).split("---\n")[1]
    quoted = json.dumps(value, ensure_ascii=False)
    assert f"source: {quoted}\n" in header
    assert f"year: {quoted}\n" in header
    assert header.count(f"  - {quoted}\n") == 2


def test_parse_reply_accepts_fenced_json_and_chatter():
    assert obsidian_note.parse_reply('前言\n```json\n{"hook":"亮點"}\n```\n後記')["hook"] == "亮點"
    assert obsidian_note.parse_reply('廢話 {not json} 然後 {"hook":"有效"}')["hook"] == "有效"


def test_parse_reply_handles_braces_inside_strings():
    hook = '字串 { 未配對 } 和 "引號" 與 \\ 跳脫 }'
    text = "前言 " + json.dumps({"hook": hook, "figures": [{"id": "a", "desc": "{"}]}) + " 尾聲"
    assert obsidian_note.parse_reply(text)["hook"] == hook


def test_parse_reply_missing_fields_defaults():
    data = obsidian_note.parse_reply('{}')
    for key in ("hook", "short", "problem", "method", "result", "limits"):
        assert data[key] == ""
    for key in ("tags", "figures", "diagrams"):
        assert data[key] == []
    assert obsidian_note.parse_reply('{"figures":[{}, {"id":"a"}]}')["figures"] == [{"id": "a", "desc": ""}]


@pytest.mark.parametrize("text", ["無 JSON", "[]", '{"hook":', '{bad}', 'null'])
def test_parse_reply_invalid_raises(text, monkeypatch):
    monkeypatch.setenv("EASYREAD_LANG", "zh-TW")
    with pytest.raises(ValueError) as error:
        obsidian_note.parse_reply(text)
    assert str(error.value) == tr("模型回复不是有效的 JSON")


def test_parse_reply_strips_fences_inside_mermaid():
    text = json.dumps({"diagrams": [{"title": "圖", "mermaid": "```mermaid\ngraph TD\nA --> B\n```"}]})
    assert obsidian_note.parse_reply(text)["diagrams"] == [{"title": "圖", "mermaid": "graph TD\nA --> B"}]


def test_parse_reply_dedupes_and_cleans_tags():
    text = json.dumps({"tags": [" #6G ", "6G", "# security tag", "\t", "##6G", "多\n行"]})
    assert obsidian_note.parse_reply(text)["tags"] == ["6G", "securitytag", "多行"]


def test_build_prompt_contains_note_style_and_json_only_instruction(ctx):
    text = obsidian_note.build_prompt(ctx, "openai")
    assert langs.NOTE_STYLE in text and langs.TW_STYLE in text
    for token in ("只回一個 JSON 物件", "不要任何其他文字", "150", "2~3", "（推論）", "不要寫「我的想法」",
                  "不要編造數據或引用", "12 字", "hook", "short", "tags", "problem", "method", "result", "limits", "figures", "diagrams"):
        assert token in text


def test_build_prompt_lists_only_figures_with_box(ctx):
    text = obsidian_note.build_prompt(ctx, "claude")
    assert "fig-a" in text and "架構圖" in text and '"page": 4' in text and '"num": 2' in text
    assert "fig-b" not in text and "不可截圖" not in text


def test_build_prompt_claude_vs_other_engine(ctx):
    claude = obsidian_note.build_prompt(ctx, "claude")
    assert "paper.json" in claude and "Read" in claude and "當前目錄" in claude
    assert ctx["text"] not in claude
    assert ctx["text"] in obsidian_note.build_prompt(ctx, "codex")
    assert ctx["text"] in obsidian_note.build_prompt(ctx, "openai")


def test_functions_do_not_mutate_inputs(ctx, data):
    before = copy.deepcopy((ctx, data))
    obsidian_note.build_prompt(ctx, "claude")
    obsidian_note.render(ctx, data, {})
    assert (ctx, data) == before


def test_parse_reply_wrong_types_are_normalized():
    text = json.dumps({"hook": None, "tags": "#tag", "figures": [None, {}, {"id": ""}], "diagrams": [None]})
    data = obsidian_note.parse_reply(text)
    assert data["hook"] == "" and data["tags"] == []
    assert data["figures"] == [] and data["diagrams"] == []
