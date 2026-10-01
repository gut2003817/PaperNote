import fitz
import pytest

from make_sample_pdf import make_sample_pdf
from paper_notes.pdf_service import PdfError, extract_figures


def test_extracts_embedded_images_and_page_renders(tmp_path):
    pdf = make_sample_pdf(tmp_path / "s.pdf")
    figs = extract_figures(pdf, tmp_path / "figures")
    names = [f.file for f in figs]
    assert "p1-1.png" in names
    assert not any(n.startswith("p2-") for n in names), "20x20 小圖應被略過"
    assert "page-1.png" in names and "page-2.png" in names
    emb = next(f for f in figs if f.file == "p1-1.png")
    assert (emb.page, emb.kind, emb.width, emb.height) == (1, "embedded", 200, 150)
    for f in figs:
        assert (tmp_path / "figures" / f.file).stat().st_size > 0


def test_vector_only_pdf_still_has_page_renders(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 300, 200), color=(0, 0, 1))
    page.insert_text((60, 80), "Figure 1: vector diagram")
    doc.save(tmp_path / "v.pdf")
    figs = extract_figures(tmp_path / "v.pdf", tmp_path / "figures")
    assert [(f.file, f.kind) for f in figs] == [("page-1.png", "page")]


def test_corrupt_pdf_raises_pdf_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(PdfError):
        extract_figures(bad, tmp_path / "figures")


def test_encrypted_pdf_raises_pdf_error(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(tmp_path / "enc.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(PdfError, match="密碼"):
        extract_figures(tmp_path / "enc.pdf", tmp_path / "figures")


def test_bad_embedded_image_does_not_prevent_page_render(tmp_path, monkeypatch):
    pdf = make_sample_pdf(tmp_path / "s.pdf")
    with fitz.open(pdf) as doc:
        bad_xref = doc[0].get_images(full=True)[0][0]
    original = fitz.Pixmap
    attempted = []

    def pixmap(*args, **kwargs):
        if len(args) == 2 and isinstance(args[0], fitz.Document):
            attempted.append(args[1])
            if args[1] == bad_xref:
                raise RuntimeError("broken embedded image")
        return original(*args, **kwargs)

    monkeypatch.setattr(fitz, "Pixmap", pixmap)
    figs = extract_figures(pdf, tmp_path / "figures")
    assert bad_xref in attempted
    assert len(attempted) == 2, "仍需繼續處理下一張圖"
    assert "p1-1.png" not in [f.file for f in figs]
    assert "page-1.png" in [f.file for f in figs]
    assert (tmp_path / "figures" / "page-1.png").stat().st_size > 0
