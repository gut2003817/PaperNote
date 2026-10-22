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
                "**方法流程**", "```mermaid", "## 結果", "![圖2", "## 其他劃線",
                "## 限制與我的想法", "### 我的想法"]
    positions = [text.index(s) for s in sections]
    assert positions == sorted(positions)
    assert "> 第一行\n> 第二行\n> （第 3 頁）\n> 筆記：待討論" in text
    assert "> 無頁碼\n\n" in text


def test_render_my_thoughts_is_empty(ctx, data):
    data["thoughts"] = "AI 不該寫的感想"
    text = obsidian_note.render(ctx, data, {})
    assert text.split("### 我的想法", 1)[1] == "\n\n"
    assert data["thoughts"] not in text


def test_render_empty_marks_and_figures_placeholders():
    text = obsidian_note.render({}, {}, {})
    assert "劃線" not in text
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
    quoted = json.dumps(value.replace("\r", ""), ensure_ascii=False)
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


def _open_fence_at_end(md: str) -> bool:
    """依 CommonMark 掃描：結尾時是否仍在程式碼圍欄內。"""
    fence = None
    for line in md.splitlines():
        if fence is None:
            m = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
            if m and not (m[1][0] == "`" and "`" in m[2]):
                fence = m[1]
        else:
            m = re.match(r"^\s{0,3}(`{3,}|~{3,})\s*$", line)
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
                fence = None
    return fence is not None


def test_render_closes_unclosed_fence_from_model(ctx, data):
    data["limits"] = "說明\n```\n未閉合圍欄"
    md = obsidian_note.render(ctx, data, {"fig-a": "a.png"}, today="2026-10-22")
    assert not _open_fence_at_end(md)
    assert md.count("### 我的想法") == 1
    after = md.split("### 我的想法")[0]
    assert "```" in after.splitlines()[-3:] or after.rstrip().endswith("```")


def test_render_backtick_info_string_is_not_a_fence(ctx, data):
    # 反引號圍欄的 info string 不能含反引號，所以這不是圍欄，下一行的標題必須被降級
    data["problem"] = "```x`y\n# 繞過H1"
    md = obsidian_note.render(ctx, data, {}, today="2026-10-22")
    assert [l for l in md.splitlines() if l.startswith("# ")] == ["# 論文標題"]


def test_render_demotes_h1_inside_list_and_quote(ctx, data):
    data["problem"] = "- # 清單內H1\n> # 引用H1\n1. # 編號H1"
    data["limits"] = "> # 限制裡的H1"
    md = obsidian_note.render(ctx, data, {}, today="2026-10-22")
    for bad in ("- # 清單內H1", "> # 引用H1", "1. # 編號H1", "> # 限制裡的H1"):
        assert bad not in md
    assert "清單內H1" in md and "引用H1" in md  # 內容保留，只降級


def test_render_keeps_headings_inside_real_code_fence(ctx, data):
    data["method"] = "```python\n# 這是程式註解\nx = 1\n```"
    md = obsidian_note.render(ctx, data, {}, today="2026-10-22")
    assert "# 這是程式註解" in md.splitlines()
    assert "### 這是程式註解" not in md


def test_render_places_figure_inline_at_marker(ctx, data):
    data['method'] = '方法前{{fig:fig-a}}方法後'
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert '方法前\n\n![圖2 整體架構](附圖/a.png)\n圖2：整體架構（第 4 頁）\n\n方法後' in md
    assert md.index('![圖2') < md.index('## 結果')


def test_render_unplaced_figure_goes_to_end_of_result(ctx, data):
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert md.index('結果說明') < md.index('![圖2') < md.index('## 其他劃線')


def test_render_places_mark_inline_and_rest_go_to_other_marks(ctx, data):
    data['problem'] = '研究問題\n{{mark:1}}\n下一點'
    md = obsidian_note.render(ctx, data, {})
    assert '研究問題\n\n> 第一行\n> 第二行\n> （第 3 頁）\n> 筆記：待討論\n\n下一點' in md
    assert '第一行' not in md.split('## 其他劃線')[1]
    assert '> 無頁碼' in md.split('## 其他劃線')[1]


def test_render_marker_used_once_duplicates_removed(ctx, data):
    data['problem'] = '{{fig:fig-a}} {{mark:1}}'
    data['method'] = '{{fig:fig-a}} {{mark:1}}'
    data['limits'] = '{{fig:fig-a}} {{mark:1}}'
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert md.count('![圖2') == md.count('> 第一行') == 1
    assert '{{' not in md


def test_render_unknown_and_invalid_markers_removed(ctx, data):
    data['problem'] = '{{mark:0}} {{mark:99}} {{mark:x}} {{fig:fig-b}} {{fig:unknown}}'
    md = obsidian_note.render(ctx, data, {'fig-b': 'unselected.png'})
    assert '{{' not in md and '![' not in md
    assert '> 第一行' in md and '> 無頁碼' in md


@pytest.mark.parametrize('fence', ['```', '~~~~'])
def test_render_marker_inside_code_fence_untouched(ctx, data, fence):
    data['method'] = f'{fence}\n{{{{fig:fig-a}}}}\n{{{{mark:1}}}}\n{fence}\n{{{{mark:1}}}}'
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert f'{fence}\n{{{{fig:fig-a}}}}\n{{{{mark:1}}}}\n{fence}' in md
    assert md.count('> 第一行') == 1
    assert md.index('![圖2') > md.index('## 結果')


def test_render_no_other_marks_section_when_all_placed(ctx, data):
    data['method'] = '{{mark:1}}{{mark:2}}'
    md = obsidian_note.render(ctx, data, {})
    assert '## 其他劃線' not in md and '## 我的劃線' not in md


def test_render_no_marks_means_no_marks_section(ctx, data):
    ctx['marks'] = []
    md = obsidian_note.render(ctx, data, {})
    assert '劃線' not in md


def test_render_my_thoughts_is_still_last_with_other_marks(ctx, data):
    data['limits'] = '限制{{mark:1}}'
    md = obsidian_note.render(ctx, data, {})
    assert md.index('## 其他劃線') < md.index('## 限制與我的想法')
    assert '第一行' not in md.split('## 其他劃線')[1].split('## 限制與我的想法')[0]
    assert md.endswith('### 我的想法\n\n')


def test_render_mark_block_page_line_inside_quote(ctx, data):
    ctx['marks'][0]['body'] = '# 想法\n第二行\n```\n未閉合'
    md = obsidian_note.render(ctx, data, {})
    assert '> 第一行\n> 第二行\n> （第 3 頁）\n> 筆記：### 想法\n> 第二行\n> ```\n> 未閉合\n> ```' in md
    assert '第 None 頁' not in md


def test_render_no_important_figures_section_anymore(ctx, data):
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert '## 重要圖表' not in md and '![圖2' in md


def test_build_prompt_numbers_marks_and_explains_markers(ctx):
    ctx['marks'][0]['quote'] = '長' * 250
    md = obsidian_note.build_prompt(ctx, 'codex')
    info = json.loads(md.split('論文資訊與讀者劃線：\n')[1].split('\n\n')[0])
    assert info['marks'] == [dict(n=1, quote='長' * 200, page=3, body='待討論'),
                             dict(n=2, quote='無頁碼', page=None, body='')]
    for token in ('{{mark:N}}', '{{fig:ID}}', '最多用一次', '其他劃線', '截斷', '結果', '單獨一行', '不要複製劃線原文'):
        assert token in md


@pytest.mark.parametrize('adjacent', ['{{mark:99}}# 標題\n---', '{{fig:fig-a}}```\n# 標題',
                                     '{{mark:1}}\n# 標題\n```'])
def test_render_inline_expansion_does_not_create_second_h1(ctx, data, adjacent):
    data['problem'] = adjacent
    data['figures'][0]['desc'] = '惡意]\n# 標題\n---\n```'
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert re.findall(r'^# .*$', md, re.M) == ['# 論文標題']
    assert not _open_fence_at_end(md)
    assert md.endswith('### 我的想法\n\n')


@pytest.mark.parametrize('html', ['<!-- x', '<pre>', '<script>', '<?php', '<![CDATA[', '<div>'])
def test_harden_html_block_line_is_escaped(html):
    assert obsidian_note._markdown('   ' + html) == '   &lt;' + html[1:]
    code = '```\n' + html + '\n```'
    assert obsidian_note._markdown(code) == code


@pytest.mark.parametrize('indent', ['\t', '\u3000', '\u00a0'])
def test_harden_tab_and_fullwidth_space_not_fence(indent):
    assert obsidian_note._markdown(indent + '```\n# evil').endswith('### evil')


def test_harden_leading_indent_not_stripped():
    assert obsidian_note._markdown('\n    ```x\n# evil\n') == '    ```x\n### evil'


def test_harden_unbalanced_percent_percent_is_closed():
    assert obsidian_note._markdown('%% hidden') == '%% hidden\n%%'


@pytest.mark.parametrize('token', ['%%', '$$'])
def test_harden_balanced_delimiters_and_code_kept(token):
    for text in (token + 'x' + token, token + '\nx\n' + token,
                 '`' + token + '`', '``x `' + token + '``',
                 '```\n# ' + token + '\n{{mark:1}}\n```'):
        assert obsidian_note._markdown(text) == text


def test_harden_unbalanced_dollar_dollar_is_closed_but_balanced_kept():
    assert obsidian_note._markdown('$$\nx') == '$$\nx\n$$'
    assert obsidian_note._markdown('$$x$$') == '$$x$$'


@pytest.mark.parametrize('prefix', ['> ', '> > ', '- ', '10. ', '    '])
def test_harden_setext_in_quote_demoted(prefix):
    assert obsidian_note._markdown(prefix + 'foo\n' + prefix + '===') == prefix + 'foo\n' + prefix + '---'


@pytest.mark.parametrize('marker', ['-', '10.'])
def test_harden_deep_indented_h1_in_list_demoted(marker):
    assert obsidian_note._markdown(marker + ' foo\n\n    # deep').endswith('    ### deep')


@pytest.mark.parametrize('field', ['quote', 'body'])
@pytest.mark.parametrize('token', ['%%', '$$'])
def test_harden_quote_with_single_percent_percent_closed(ctx, field, token):
    ctx['marks'] = [{'quote': 'quote', 'body': '', field: token + ' text'}]
    md = obsidian_note.render(ctx, {}, {})
    assert '> ' + token + '\n\n## 限制' in md


def test_harden_control_and_surrogate_chars_removed(ctx, data):
    bad = ''.join(chr(n) for n in range(160) if n < 32 and n not in (9, 10) or 127 <= n <= 159)
    bad += '\ud800\udfff\ufffe\uffff'
    value = 'keep' + bad + 'text'
    ctx.update(title=value, authors=[value], source=value, year=value,
               marks=[{'quote': value, 'body': value, 'page': value}])
    ctx['figures'][0].update(num=value, page=value)
    data.update({key: value for key in ('hook', 'short', 'problem', 'method', 'result', 'limits')})
    data.update(tags=[value], diagrams=[{'title': value, 'mermaid': value}])
    data['figures'][0]['desc'] = value
    md = obsidian_note.render(ctx, data, {'fig-a': value + '.png'}, today=value)
    md.encode('utf-8')
    assert all(char not in md for char in bad)
    assert 'keeptext' in md
    assert obsidian_note._yaml(value) == '"keeptext"'
    assert obsidian_note._inline(value) == 'keeptext'
    assert obsidian_note._markdown(value) == 'keeptext'


@pytest.mark.parametrize('token', ['%%', '$$'])
def test_harden_inline_delimiters_closed(ctx, data, token):
    ctx['title'] = token
    data['diagrams'][0]['title'] = token
    data['figures'][0]['desc'] = token
    md = obsidian_note.render(ctx, data, {'fig-a': 'a.png'})
    assert '# ' + token + ' ' + token + '\n' in md
    assert '**' + token + ' ' + token + '**' in md
    assert '圖2：' + token + ' ' + token + '（' in md


def test_harden_mark_body_initial_fence_remains_real(ctx):
    ctx['marks'] = [{'quote': 'quote', 'body': '```\n\n- foo\n\n    # deep\n```'}]
    md = obsidian_note.render(ctx, {}, {})
    assert '> 筆記：\n> ```\n' in md


def test_harden_indented_code_delimiters_not_counted():
    text = '    ``` $$\ntext'
    assert obsidian_note._markdown(text) == text


def test_harden_quote_fence_delimiters_not_counted():
    text = '> ```\n> $$ %%\n> ```'
    assert obsidian_note._markdown(text) == text


def test_harden_inline_html_comment_cannot_hide_delimiters():
    assert '<!--' not in obsidian_note._markdown('\ufeff <!--\n%%-->')


@pytest.mark.parametrize('token', ['%%', '$$'])
def test_harden_delimiters_in_list_continuation_closed(token):
    text = '- foo\n\n    # deep ' + token
    assert obsidian_note._markdown(text).endswith('\n' + token)


def test_harden_list_continuation_fence_closed_before_delimiter():
    text = 'text$$\n1. item\n\n    ```'
    cleaned = obsidian_note._markdown(text)
    assert cleaned.endswith('    ```\n    ```\n$$')


def test_harden_list_fence_ends_with_container():
    text = '- item\n\n    ```\n---\n\n- foo\n\n    # deep'
    assert obsidian_note._markdown(text).endswith('    ### deep')
    text = '- item\n\n    ```\n```'
    assert obsidian_note._markdown(text).endswith('\n```\n```')


def test_harden_mermaid_cleaned_before_fence_filter(ctx):
    md = obsidian_note.render(ctx, {'diagrams': [{'mermaid': '\x00```\n# x\n\ud800```'}]}, {})
    assert '```mermaid\n# x\n```' in md


def test_harden_inline_code_does_not_cross_blank_lines():
    assert obsidian_note._markdown('`\n\n$$\n\n`').endswith('\n$$')


def test_harden_quoted_fence_inside_plain_code_is_not_closer():
    text = '```\n> ```\n# code\n%% $$ {{mark:1}}\n```'
    assert obsidian_note._markdown(text) == text


@pytest.mark.parametrize('engine,digest', [
    ('claude', '8d90db6377ad1bb9ab035a158ae582b7c668146515f0aee0e34376b972259c5e'),
    ('codex', '0ba04124962bbc6833b5f6d7378fdf31c79e6b383eed5a90b6cdcd7178a918a4'),
    ('openai', '0ba04124962bbc6833b5f6d7378fdf31c79e6b383eed5a90b6cdcd7178a918a4')])
def test_build_prompt_without_ai_images_unchanged(ctx, engine, digest):
    import hashlib
    assert hashlib.sha256(obsidian_note.build_prompt(ctx, engine, ai_images=False).encode()).hexdigest() == digest


def test_build_prompt_with_ai_images_explains_field_and_img_marker(ctx):
    text = obsidian_note.build_prompt(ctx, 'codex', ai_images=True)
    for token in ('ai_images', 'cover', 'explain', '{{img:N}}', '英文', '0~3', '文字、字母、數字', '標誌'):
        assert token in text


def test_parse_reply_ai_images_normalized():
    cover = {'kind': 'cover', 'desc': 42, 'prompt': 'a' * 1600}
    explain = {'kind': 'explain', 'desc': 'concept', 'prompt': 'scene'}
    raw = [None, {}, {'kind': 'bad', 'prompt': 'x'}, {'kind': 'explain', 'prompt': '  '},
           {'kind': 'cover', 'prompt': None}, explain, cover, {'kind': 'cover', 'prompt': 'second'}] + [explain] * 4
    parsed = obsidian_note.parse_reply(json.dumps({'ai_images': raw}))['ai_images']
    assert parsed == [dict(cover, desc='', prompt='a' * 1500)] + [explain] * 3
    assert obsidian_note.parse_reply('{}')['ai_images'] == []


@pytest.fixture
def ai_data(data):
    data['ai_images'] = [{'kind': 'cover', 'desc': '核心', 'prompt': 'cover'},
                         {'kind': 'explain', 'desc': '原理', 'prompt': 'first'},
                         {'kind': 'explain', 'desc': '流程', 'prompt': 'second'}]
    return data


AI_FILES = {'cover': 'cover.png', 'explain-1': 'first.png', 'explain-2': 'second.png'}


def test_render_cover_after_hook(ctx, ai_data):
    text = obsidian_note.render(ctx, ai_data, {}, ai_files=AI_FILES)
    assert text.index(ai_data['hook']) < text.index('cover.png') < text.index('## 問題與動機')


def test_render_img_marker_inline_and_unplaced_after_method(ctx, ai_data):
    ai_data['problem'] = 'before {{img:1}} after'
    text = obsidian_note.render(ctx, ai_data, {}, ai_files=AI_FILES)
    assert text.index('before') < text.index('first.png') < text.index('after') < text.index('## 方法重點')
    assert text.index('方法說明') < text.index('second.png') < text.index('```mermaid')


def test_render_img_invalid_and_duplicate_removed(ctx, ai_data):
    ai_data['method'] = '{{img:1}} {{img:1}} {{img:0}} {{img:-1}} {{img:x}} {{img:3}} {{img:' + '9' * 5000 + '}}'
    ai_data['limits'] = '```\n{{img:2}}\n```'
    text = obsidian_note.render(ctx, ai_data, {}, ai_files=AI_FILES)
    assert text.count('first.png') == 1 and text.count('second.png') == 1
    assert text.count('{{img:') == 1 and '```\n{{img:2}}\n```' in text


def test_render_no_ai_files_output_identical_to_before(ctx, data):
    import hashlib
    text = obsidian_note.render(ctx, data, {'fig-a': 'a.png'}, today='2026-10-22', ai_files={})
    assert hashlib.sha256(text.encode()).hexdigest() == 'a133a34ded82936dcb7e8e82dbe637ee43f72f9c9da5b298c5ed5f6778c1db3e'
    data['method'] += '{{img:1}} {{img:bad}}'
    assert '{{img:' not in obsidian_note.render(ctx, data, {})


def test_render_ai_image_labeled_as_ai_generated(ctx, ai_data):
    text = obsidian_note.render(ctx, ai_data, {}, ai_files={'cover': 'a b(#).png'})
    assert '![示意圖（AI 生成） 核心](附圖/a%20b%28%23%29.png)\n示意圖（AI 生成）：核心' in text


def test_render_ai_desc_injection_no_second_h1(ctx, ai_data):
    for image in ai_data['ai_images']:
        image['desc'] = ']\n# injected\n```\n%% $$\x00'
    text = obsidian_note.render(ctx, ai_data, {}, ai_files=AI_FILES)
    assert re.findall(r'^# .*$', text, re.M) == ['# 論文標題']
    assert '\\]' in text and '\x00' not in text
    assert not _open_fence_at_end(text) and text.endswith('### 我的想法\n\n')


def test_render_hook_img_deletion_cannot_create_heading(ctx, data):
    data['hook'] = '#{{img:1}} injected\n```\n{{img:1}}\n```'
    text = obsidian_note.render(ctx, data, {})
    assert re.findall(r'^# .*$', text, re.M) == ['# 論文標題']
    assert '```\n{{img:1}}\n```' in text


def test_render_ai_desc_cannot_open_html_comment(ctx, ai_data):
    ai_data['ai_images'][0]['desc'] = '<!-- injected'
    text = obsidian_note.render(ctx, ai_data, {}, ai_files=AI_FILES)
    assert '<!--' not in text
