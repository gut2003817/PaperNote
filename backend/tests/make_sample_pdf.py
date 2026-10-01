"""產生測試用 PDF：第 1 頁有文字與一張 200x150 圖；第 2 頁有文字與一張 20x20 小圖。"""
import sys
from pathlib import Path

import fitz


def _png(w: int, h: int, gray: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.clear_with(gray)
    return pix.tobytes("png")


def make_sample_pdf(path: Path) -> Path:
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Sample Paper Title", fontsize=20)
    p1.insert_image(fitz.Rect(72, 100, 272, 250), stream=_png(200, 150, 180))
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Results", fontsize=14)
    p2.insert_image(fitz.Rect(72, 100, 92, 120), stream=_png(20, 20, 90))
    doc.save(path)
    doc.close()
    return Path(path)


if __name__ == "__main__":
    make_sample_pdf(Path(sys.argv[1]))
