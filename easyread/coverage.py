"""漏段检测：PDF 文字层（extract/page-NNN.txt）里有整段正文没进任何块。只检测，不补译、不调模型。

做法：把整篇论文所有块的原文（en / 图说 / 图内文字 / 列表 / 表格 / 元数据 / 参考文献）正规化成只留 [a-z0-9]，
逐页逐行去比：用 30 字符的窗口在语料里找，窗口命中的位置算“已收”。整行（或整行 70% 以上）没被收的行连成一段，
再丢掉图内零碎文字、作者单位脚注、页眉页脚，剩下连续 >= 80 字符且含完整句子的才报。
"""
from __future__ import annotations

import json
import re

from .app.i18n import tr
from .library.store import Workspace

WINDOW = 30  # 比对窗口（正规化后的字符数）
MIN_CHARS = 80  # 一段连续缺漏至少这么多字符才报
SHORT_LINE = 40  # 有图的页上，短于这个长度且不以句号结尾的未收行，当作图内文字
LINE_COVERED = 0.7  # 一行里被收的字符占比达到这个值，算已收

# 页眉页脚、纯页码
_DROP_LINE = [
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"Authorized licensed use limited to", re.I),
    re.compile(r"Digital Object Identifier|^\s*\d{4}-\d{3}[\dxX]/", re.I),
    re.compile(r"^\s*\d{0,4}\s*[A-Z][\w .&-]{3,60}[•·|]\s*(?:[A-Z][a-z]+\.?\s+)?\d{4}\s*\d{0,4}\s*$"),  # 期刊名 • 日期 页码 / 页码 期刊名 • 日期
    re.compile(r"[•·|]\s*(?:[A-Z][a-z]+\.?\s+)?\d{4}\s+\d{1,4}\s*$"),
    re.compile(r"©\s*\d{4}"),
]
_REF_HEAD = re.compile(r"^\s*(?:\d+\.?\s*)?(references|bibliography)\s*$", re.I)
_CAPTION = re.compile(r"^\s*(FIGURE|Figure|Fig\.|TABLE|Table)\s*\d+")
# 第一页的作者 / 单位 / 通讯作者脚注
_AFFIL = re.compile(r"\b(?:is|are|also|was|were)\s+with\b|corresponding author|\bsenior member\b|\bmember,? IEEE\b|\bfellow,? IEEE\b|@[\w.-]+\.\w+|\bemail\b", re.I)
_SENT_END = re.compile(r"[.?!][\"')\]]?(?:\s|$)")
_CTRL = re.compile("[\x00-\x08\x0b-\x1f\x7f]")
_NONALNUM = re.compile(r"[^a-z0-9]")


def _norm(s: str) -> str:
    return _NONALNUM.sub("", s.lower())


def _corpus(paper: dict) -> str:
    parts: list[str] = []
    meta = paper.get("meta", {}) or {}
    for k in ("title_en", "abstract_en", "authors", "affiliation", "venue", "doi", "date"):
        parts.append(str(meta.get(k) or ""))
    for r in paper.get("references") or []:
        parts.append(str(r.get("text") or "") if isinstance(r, dict) else str(r))
    for b in paper.get("blocks", []) or []:
        if not isinstance(b, dict):
            continue
        for k in ("en", "caption_en", "image_en", "title_en", "tex"):
            if isinstance(b.get(k), str):
                parts.append(b[k])
        items = b.get("items")
        for it in items if isinstance(items, list) else []:
            parts.append(str(it.get("en") or "") if isinstance(it, dict) else str(it))
        for field in ("head", "rows"):
            if isinstance(b.get(field), list):
                parts.append(json.dumps(b[field], ensure_ascii=False))
    return "|".join(_norm(x) for x in parts)  # | 隔开，窗口不会跨块误命中


def _clean_lines(text: str) -> tuple[list[str], bool]:
    """去页眉页脚、References 之后的内容。返回 (行, 这页出现了 References 标题)。"""
    lines = [_CTRL.sub("", raw).rstrip() for raw in text.splitlines()]
    lines = [ln for ln in lines if ln.strip() and not any(r.search(ln) for r in _DROP_LINE)]
    for i, ln in enumerate(lines):
        if _REF_HEAD.match(ln):
            return lines[:i], True
    return lines, False


def _mask(ns: str, cor: str) -> bytearray:
    m = bytearray(len(ns))
    for i in range(max(0, len(ns) - WINDOW + 1)):
        if ns[i:i + WINDOW] in cor:
            m[i:i + WINDOW] = b"\x01" * WINDOW
    return m


def _meta_words(paper: dict) -> set[str]:
    meta = paper.get("meta", {}) or {}
    text = " ".join(str(meta.get(k) or "") for k in ("title_en", "authors", "affiliation", "venue", "doi", "date"))
    return set(re.findall(r"[a-z]{2,}", text.lower()))


def _front_matter(line: str, words: set[str]) -> bool:
    """第一页的作者名单、单位、通讯作者脚注：词大部分出现在 meta 里，或有“X is with …”句式。"""
    if _AFFIL.search(line):
        return True
    ws = re.findall(r"[a-z]{2,}", line.lower())
    return len(ws) >= 3 and sum(w in words for w in ws) / len(ws) >= 0.8


def _join(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and ln[:1].islower():
            out = out[:-1] + ln  # 连字号断行：satel- / lite
        else:
            out = f"{out} {ln}" if out else ln
    return out.strip()


def _page_gaps(n: int, text: str, cor: str, has_figure: bool, words: set[str]) -> list[dict]:
    lines, _ = _clean_lines(text)
    if not lines:
        return []
    norms = [_norm(ln) for ln in lines]
    ns = "".join(norms)
    mask = _mask(ns, cor)
    # 每行：被收字符占比；整行直接在语料里也算已收（短行、标题、列表项）
    state: list[str] = []  # covered / noise / gap
    spans, pos = [], 0
    for ln, nl in zip(lines, norms):
        spans.append((pos, pos + len(nl)))
        pos += len(nl)
        frac = (sum(mask[spans[-1][0]:spans[-1][1]]) / len(nl)) if nl else 1.0
        if len(nl) < 3 or frac >= LINE_COVERED or nl in cor:
            state.append("covered")
        elif has_figure and (_CAPTION.match(ln) or (len(ln.strip()) < SHORT_LINE and not _SENT_END.search(ln[-3:] + " "))):
            state.append("noise")  # 图内标签、零碎短行
        elif n == 1 and _front_matter(ln, words):
            state.append("noise")  # 作者、单位脚注
        else:
            state.append("gap")
    gaps, cur = [], []  # cur: 行下标；noise 行不打断也不计入
    for i, s in enumerate(state + ["covered"]):
        if s == "gap":
            cur.append(i)
        elif s == "covered" and cur:
            first = cur[0]
            # 前一行末尾几个词若没被收（句子从上一行末尾开头：「… network. For」），并进来
            head = ""
            if first > 0 and state[first - 1] == "covered":
                a, b = spans[first - 1]
                k = 0
                while k < b - a and not mask[b - 1 - k]:
                    k += 1
                if 0 < k <= 15:
                    words_ = lines[first - 1].split()
                    head = words_[-1] if words_ else ""
            text_ = _join(([head] if head else []) + [lines[j] for j in cur])
            if len(text_) >= MIN_CHARS and _SENT_END.search(text_ + " "):
                gaps.append({"page": n, "chars": len(text_), "text": text_})
            cur = []
    return gaps


def find_gaps(ws: Workspace) -> list[dict]:
    """返回 [{page, chars, text}]。没有 extract 或没有块（还没译、只导入）时返回空表，不报错。"""
    try:
        paper = ws.load("paper")
        blocks = paper.get("blocks") or []
        if not blocks:
            return []
        meta = paper.get("meta", {}) or {}
        tl = paper.get("translation", {}) or {}
        # 只查已经有块或标记为已完成的页；部分翻译时没动过的页不算漏
        pages = {b.get("page") for b in blocks if isinstance(b, dict)} | set(tl.get("done_pages", []))
        figure_pages = {b.get("page") for b in blocks if isinstance(b, dict) and b.get("type") in ("figure", "table")}
        cor = _corpus(paper)
        words = _meta_words(paper)
        total = int(meta.get("page_count") or 0) or max((p for p in pages if isinstance(p, int)), default=0)
        out: list[dict] = []
        for n in range(1, total + 1):
            f = ws.root / "extract" / f"page-{n:03d}.txt"
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if n in pages:
                out += _page_gaps(n, text, cor, n in figure_pages, words)
            if _clean_lines(text)[1]:
                break  # References 之后（作者简介、版权页）不查
        return out
    except Exception:  # noqa: BLE001  检测是辅助功能，任何意外都不该拖垮 check / 翻译
        return []


def describe(g: dict, pid: str) -> str:
    snippet = g["text"][:80] + ("…" if len(g["text"]) > 80 else "")
    return tr("第 {page} 页疑似漏掉约 {chars} 字：“{snippet}”", page=g["page"], chars=g["chars"], snippet=snippet)


def hint(pid: str, gaps: list[dict]) -> str:
    n = gaps[0]["page"]
    return tr("补救：可用 `easyread translate {id} --pages {a},{b}`（两页放同一批）重译，或用 `easyread blocks {id} --from 文件` 手动补。",
              id=pid, a=max(1, n - 1), b=n)


def report_lines(pid: str, gaps: list[dict]) -> list[str]:
    if not gaps:
        return [tr("漏段检查通过：正文每段都进了块")]
    return [tr("疑似漏段 {n} 处：", n=len(gaps))] + ["- " + describe(g, pid) for g in gaps] + [hint(pid, gaps)]
