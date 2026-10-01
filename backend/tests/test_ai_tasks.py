import json

import pytest

from fakes import FakeRun
from paper_notes.ai_runner import AIError
from paper_notes.ai_tasks import AIFormatError, edit_selection, generate_note, generate_summary
from paper_notes.pdf_service import FigureInfo

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]}}
FIGS = [FigureInfo("p3-1.png", 3, "embedded", 400, 300), FigureInfo("page-3.png", 3, "page", 900, 1200)]


def blocks_out(blocks, reply="ok"):
    return {"reply": reply, "blocks_json": json.dumps(blocks, ensure_ascii=False)}


def test_generate_summary(tmp_path):
    run = FakeRun([{"summary_md": "# 摘要\n" + "重點內容。" * 20}])
    assert generate_summary("claude", tmp_path, run=run).startswith("# 摘要")
    assert "paper.pdf" in run.prompts[0]


def test_generate_summary_too_short(tmp_path):
    with pytest.raises(AIFormatError):
        generate_summary("claude", tmp_path, run=FakeRun([{"summary_md": "短"}]))


def test_generate_note_assigns_ids_and_forces_unverified(tmp_path):
    run = FakeRun([blocks_out([
        {"id": "dup", "type": "heading", "level": 1, "text": "標題"},
        {"type": "chart", "spec": BAR, "source": "Table 1, p.5", "verified": True},
        {"type": "figure", "path": "p3-1.png", "caption": "架構", "page": 3},
    ])])
    blocks = generate_note("codex", tmp_path, "摘要", FIGS, run=run)
    assert [b.type for b in blocks] == ["heading", "chart", "figure"]
    assert blocks[0].id != "dup"
    assert blocks[1].verified is False
    assert "p3-1.png" in run.prompts[0] and "摘要" in run.prompts[0]
    assert run.engines == ["codex"]


@pytest.mark.parametrize("bad", [
    {"reply": "ok", "blocks_json": "not json"},
    blocks_out([{"type": "chart", "spec": {"data": {}}, "source": ""}]),
    blocks_out([{"type": "figure", "path": "made-up.png", "page": 1}]),
    blocks_out([]),
    {"reply": "ok"},
])
def test_generate_note_retries_once_then_succeeds(tmp_path, bad):
    run = FakeRun([bad, blocks_out([{"type": "paragraph", "text": "好"}])])
    blocks = generate_note("claude", tmp_path, "摘要", FIGS, run=run)
    assert blocks[0].text == "好"
    assert len(run.prompts) == 2
    assert "上一次的輸出格式有誤" in run.prompts[1]


def test_generate_note_fails_after_two_bad_outputs(tmp_path):
    bad = {"reply": "ok", "blocks_json": "[{]"}
    with pytest.raises(AIFormatError) as ei:
        generate_note("claude", tmp_path, "摘要", FIGS, run=FakeRun([bad, bad]))
    assert "[{]" in ei.value.raw


def test_runner_error_propagates_without_retry(tmp_path):
    run = FakeRun([AIError("claude 超過 300 秒未完成，已中止")])
    with pytest.raises(AIError, match="300"):
        generate_note("claude", tmp_path, "摘要", FIGS, run=run)
    assert len(run.prompts) == 1


def _edit(run, **kw):
    args = dict(engine="claude", paper_dir=kw.pop("paper_dir"), summary="摘要",
                selected=[{"id": "p1", "type": "paragraph", "text": "原文"}],
                selected_text="這一句", before={"id": "h", "type": "heading", "level": 2, "text": "方法"},
                after=None, message="改白話一點", figures=["p3-1.png"], run=run)
    args.update(kw)
    return edit_selection(**args)


def test_edit_replace(tmp_path):
    run = FakeRun([blocks_out([{"type": "paragraph", "text": "新文"}], reply="已改寫")])
    res = _edit(run, paper_dir=tmp_path)
    assert res.reply == "已改寫" and res.replace[0].text == "新文"
    p = run.prompts[0]
    assert "改白話一點" in p and "這一句" in p and "原文" in p and "方法" in p


def test_edit_reply_only(tmp_path):
    res = _edit(FakeRun([{"reply": "這是在說…", "blocks_json": ""}]), paper_dir=tmp_path)
    assert res.replace is None and res.reply == "這是在說…"


def test_edit_inside_column_rejects_columns_then_retries(tmp_path):
    cols = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]}]}
    run = FakeRun([blocks_out([cols]), blocks_out([{"type": "paragraph", "text": "ok"}])])
    res = _edit(run, paper_dir=tmp_path, allow_columns=False)
    assert res.replace[0].type == "paragraph"
    assert "並排欄位內" in run.prompts[0] and "上一次的輸出格式有誤" in run.prompts[1]
