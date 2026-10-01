import time

import pytest

from paper_notes.schema import Note
from paper_notes.storage import NotFound, Storage


@pytest.fixture
def st(tmp_path):
    return Storage(tmp_path / "papers")


def _note(text):
    return Note.model_validate({"blocks": [{"id": "p1", "type": "paragraph", "text": text}]})


def test_create_and_list(st):
    slug = st.create_paper("Attention Is All You Need", b"%PDF-1.4 fake")
    assert slug.startswith("attention-is-all-you-need-")
    assert (st.paper_dir(slug) / "paper.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert st.figures_dir(slug).is_dir()
    [info] = st.list_papers()
    assert info.slug == slug and info.title == "Attention Is All You Need" and info.has_note is False


def test_chinese_title_gets_generic_slug(st):
    slug = st.create_paper("注意力機制", b"%PDF")
    assert slug.startswith("paper-")
    assert st.list_papers()[0].title == "注意力機制"


def test_list_sorted_newest_first(st):
    a = st.create_paper("a", b"%PDF")
    time.sleep(0.01)
    b = st.create_paper("b", b"%PDF")
    assert [p.slug for p in st.list_papers()] == [b, a]


@pytest.mark.parametrize("slug", ["../etc", "nope", "A-B", ""])
def test_bad_or_missing_slug(st, slug):
    with pytest.raises(NotFound):
        st.paper_dir(slug)


def test_note_round_trip_and_has_note(st):
    slug = st.create_paper("x", b"%PDF")
    with pytest.raises(NotFound):
        st.read_note(slug)
    st.write_note(slug, _note("hello"))
    assert st.read_note(slug).blocks[0].text == "hello"
    assert st.list_papers()[0].has_note is True
    assert "heightPx" not in (st.paper_dir(slug) / "note.json").read_text()


def test_summary_default_empty(st):
    slug = st.create_paper("x", b"%PDF")
    assert st.read_summary(slug) == ""
    st.write_summary(slug, "# 摘要")
    assert st.read_summary(slug) == "# 摘要"


def test_snapshot_without_note_raises_not_found(st):
    slug = st.create_paper("x", b"%PDF")
    with pytest.raises(NotFound) as exc:
        st.snapshot(slug)
    assert str(exc.value) == f"{slug}/note.json"


def test_snapshot_and_restore(st):
    slug = st.create_paper("x", b"%PDF")
    st.write_note(slug, _note("v1"))
    name = st.snapshot(slug)
    st.write_note(slug, _note("v2"))
    restored = st.restore(slug, name)
    assert restored.blocks[0].text == "v1"
    assert st.read_note(slug).blocks[0].text == "v1"


@pytest.mark.parametrize("name", ["../note.json", "20260101-000000-zzzz.json", "x.json"])
def test_restore_rejects_bad_names(st, name):
    slug = st.create_paper("x", b"%PDF")
    st.write_note(slug, _note("v1"))
    with pytest.raises(NotFound):
        st.restore(slug, name)


def test_chat_append_and_read(st):
    slug = st.create_paper("x", b"%PDF")
    assert st.read_chat(slug) == []
    st.append_chat(slug, {"role": "user", "text": "你好"})
    st.append_chat(slug, {"role": "assistant", "text": "嗨"})
    chat = st.read_chat(slug)
    assert [c["text"] for c in chat] == ["你好", "嗨"]
    assert all("ts" in c for c in chat)


def test_figure_path_validation(st):
    slug = st.create_paper("x", b"%PDF")
    (st.figures_dir(slug) / "p1-1.png").write_bytes(b"png")
    assert st.figure_path(slug, "p1-1.png").exists()
    for bad in ["../paper.pdf", "missing.png", "p1-1.jpg"]:
        with pytest.raises(NotFound):
            st.figure_path(slug, bad)
