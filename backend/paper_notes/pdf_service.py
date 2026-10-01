"""從 PDF 擷取圖片：嵌入的點陣圖，加上每頁整頁截圖（論文常見的向量圖靠這個）。"""
from dataclasses import dataclass
from pathlib import Path

import fitz


class PdfError(Exception):
    pass


@dataclass
class FigureInfo:
    file: str
    page: int
    kind: str  # "embedded" | "page"
    width: int
    height: int


def extract_figures(pdf_path: Path, out_dir: Path, min_side: int = 120,
                    page_zoom: float = 1.5) -> list[FigureInfo]:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise PdfError(f"無法開啟 PDF：{e}") from e
    with doc:
        if doc.needs_pass:
            raise PdfError("PDF 有密碼保護，請先移除密碼再上傳")
        if doc.page_count == 0:
            raise PdfError("PDF 沒有任何頁面")
        out_dir.mkdir(parents=True, exist_ok=True)
        figures: list[FigureInfo] = []
        seen: set[int] = set()
        for pno, page in enumerate(doc, start=1):
            for i, img in enumerate(page.get_images(full=True), start=1):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                pix = fitz.Pixmap(doc, xref)
                if pix.width < min_side or pix.height < min_side:
                    continue
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                name = f"p{pno}-{i}.png"
                pix.save(out_dir / name)
                figures.append(FigureInfo(name, pno, "embedded", pix.width, pix.height))
            render = page.get_pixmap(matrix=fitz.Matrix(page_zoom, page_zoom))
            name = f"page-{pno}.png"
            render.save(out_dir / name)
            figures.append(FigureInfo(name, pno, "page", render.width, render.height))
    return figures
