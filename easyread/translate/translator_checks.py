"""翻译记录 job.log，和模型报的原文问题 → 页边的“原文核对提示”。"""
from __future__ import annotations

from . import sentences
from ..app.i18n import tr
from ..library.paperdata import add_discussion
from ..library.store import Workspace, now_iso


def journal(ws: Workspace, line: str) -> None:
    """每篇论文自己的翻译记录 job.log，页面上“查看记录”看的就是它。"""
    with open(ws.root / "job.log", "a", encoding="utf-8") as f:
        f.write(f"{now_iso()[:19].replace('T', ' ')}  {line}\n")


def save_checks(ws: Workspace, checks, batch: list[int]) -> None:
    """模型发现的原文问题 → 页边的“原文核对提示”。重译这几页时，先去掉上次翻译留下的那几条。"""
    pages = {b["id"]: b.get("page") for b in ws.load("paper").get("blocks", [])}
    old = [e["id"] for e in ws.load("discussion").get("entries", [])
           if e.get("kind") == "check" and e.get("by") == "translator" and pages.get(e.get("anchor")) in batch]
    if old:
        ws.update("discussion", lambda d: d.__setitem__("entries", [e for e in d["entries"] if e.get("id") not in old]))
    items = [{"kind": "check", "by": "translator", "anchor": c["anchor"], "quote": sentences.strip(str(c.get("quote") or ""))[:200],
              "title": str(c.get("title") or "")[:80], "body": str(c["body"])}
             for c in (checks or []) if isinstance(c, dict) and c.get("anchor") in pages and str(c.get("body") or "").strip()]
    if items:
        try:
            add_discussion(ws, items)
        except ValueError as e:
            journal(ws, tr("核对提示没存上：{err}", err=e))
