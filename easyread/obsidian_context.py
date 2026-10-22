"""从论文目录只读蒐集 Obsidian 笔记所需的事实素材。"""
from __future__ import annotations

import re

from .library.store import Workspace

PAPER_BUDGET = 14000


def _paper_text(blocks: list[dict]) -> str:
    """优先用译文，参考文献之后不收；换行也计入字数上限。"""
    out, used = [], 0
    for b in blocks:
        kind = b.get("type")
        if kind == "references":
            break
        if kind == "list":
            text = "\n".join(f"- {it.get('zh') or it.get('en') or ''}" for it in b.get("items", []))
        elif kind in ("figure", "table"):
            text = "\n".join(filter(None, [b.get("caption_zh") or b.get("caption_en"),
                                           b.get("image_zh") or b.get("image_en")]))
        elif kind == "math":
            text = f"$${b.get('tex') or ''}$$"
        else:
            text = b.get("zh") or b.get("en") or ""
            if text and kind == "heading":
                text = "## " + text
        if not text:
            continue
        remaining = PAPER_BUDGET - used - bool(out)
        if remaining <= 0:
            break
        out.append(text[:remaining])
        used += len(out[-1]) + (len(out) > 1)
        if used == PAPER_BUDGET:
            break
    return "\n".join(out)


def _source(meta: dict) -> str:
    """来源优先 DOI，其次 arXiv，最后使用已填写的网址。"""
    doi = meta.get("doi") or ""
    if doi:
        return doi if doi.startswith(("https://doi.org/", "http://doi.org/")) else f"https://doi.org/{doi}"
    arxiv = meta.get("arxiv") or ""
    if arxiv:
        return arxiv if arxiv.startswith(("https://", "http://")) else f"https://arxiv.org/abs/{arxiv}"
    return meta.get("url") or ""


def collect(ws: Workspace) -> dict:
    """合并用户覆写的元数据，按原文顺序收集带页码的引用和可选图表。"""
    paper = ws.load("paper") or {}
    reader = ws.load("reader") or {}
    item = ws.load("item") or {}
    meta = dict(paper.get("meta") or {})
    # 与 library.summary 一致：空覆写不生效，唯独 DOI 可以主动清空。
    meta.update({k: v for k, v in (item.get("meta_override") or {}).items() if v or k == "doi"})
    year = meta.get("year")
    if not year:
        match = re.search(r"(19|20)\d{2}", meta.get("date") or "")
        year = match.group(0) if match else ""

    blocks = paper.get("blocks") or []
    by_id = {b["id"]: b for b in blocks if b.get("id") is not None}
    order = {b["id"]: i for i, b in enumerate(blocks) if b.get("id") is not None}
    notes = [n for n in (reader.get("notes") or {}).values() if not n.get("deleted") and n.get("quote")]
    notes.sort(key=lambda n: order.get(n.get("anchor"), len(blocks)))
    marks = [{
        "quote": n["quote"],
        "page": by_id.get(n.get("anchor"), {}).get("page"),
        "side": n.get("side") or "",
        "body": n.get("body") or "",
    } for n in notes]
    figures = [{
        "id": b["id"], "num": b.get("num"), "page": b["page"],
        "caption": b.get("caption_en") or b.get("caption_zh") or "",
        "type": b["type"], "has_box": bool(b.get("box")),
    } for b in blocks if b.get("type") in ("figure", "table")]
    return {
        "title": meta.get("title_en") or meta.get("title_zh") or "",
        "authors": [a.strip() for a in (meta.get("authors") or "").split(",") if a.strip()],
        "year": str(year), "source": _source(meta),
        "marks": marks, "figures": figures, "text": _paper_text(blocks),
    }
