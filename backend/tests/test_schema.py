import pytest
from pydantic import ValidationError

from paper_notes.schema import BlockList, Note, flatten

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]},
       "encoding": {"x": {"field": "x"}, "y": {"field": "y", "type": "quantitative"}}}


def test_valid_note_with_all_block_types_and_auto_ids():
    note = Note.model_validate({"blocks": [
        {"type": "heading", "level": 1, "text": "標題"},
        {"type": "paragraph", "text": "**粗體**"},
        {"type": "eli5", "text": "像是..."},
        {"type": "chart", "spec": BAR, "source": "Table 2, p.7"},
        {"type": "diagram", "mermaid": "flowchart LR\n A-->B"},
        {"type": "figure", "path": "p3-1.png", "caption": "架構", "page": 3,
         "layout": {"widthPct": 50, "align": "left"}},
        {"type": "whiteboard"},
        {"type": "columns", "columns": [
            {"widthPct": 40, "blocks": [{"type": "paragraph", "text": "左"}]},
            {"widthPct": 60, "blocks": [{"type": "eli5", "text": "右"}]},
        ]},
    ]})
    assert len(note.blocks) == 8
    assert all(len(b.id) == 10 for b in note.blocks)
    assert note.blocks[3].verified is False
    assert note.blocks[5].layout.widthPct == 50
    assert note.blocks[6].scene == {"elements": []}


def test_chart_spec_without_view_key_rejected():
    with pytest.raises(ValidationError, match="mark"):
        BlockList.validate_python([{"type": "chart", "spec": {"data": {}}, "source": ""}])


def test_columns_widths_must_sum_to_100():
    with pytest.raises(ValidationError, match="100"):
        BlockList.validate_python([{"type": "columns", "columns": [
            {"widthPct": 30, "blocks": [{"type": "paragraph", "text": "a"}]},
            {"widthPct": 30, "blocks": [{"type": "paragraph", "text": "b"}]},
        ]}])


def test_columns_cannot_nest():
    inner = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]},
    ]}
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "columns", "columns": [
            {"widthPct": 50, "blocks": [inner]},
            {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "c"}]},
        ]}])


@pytest.mark.parametrize("path", ["../secret.png", "a/b.png", "x.jpg", ""])
def test_figure_path_rejects_traversal_and_non_png(path):
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "figure", "path": path, "page": 1}])


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "paragraph", "text": "a", "color": "red"}])


def test_heading_level_limited_to_3():
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "heading", "level": 4, "text": "a"}])


def test_flatten_document_order():
    blocks = BlockList.validate_python([
        {"id": "a", "type": "paragraph", "text": "a"},
        {"id": "c", "type": "columns", "columns": [
            {"widthPct": 50, "blocks": [{"id": "c1", "type": "paragraph", "text": "1"}]},
            {"widthPct": 50, "blocks": [{"id": "c2", "type": "paragraph", "text": "2"}]},
        ]},
        {"id": "z", "type": "paragraph", "text": "z"},
    ])
    assert [b.id for b in flatten(blocks)] == ["a", "c", "c1", "c2", "z"]
