"""导出带划线的 PDF：把阅读页上的划线 / 底线（含笔记内文）写成标准 PDF 注解，输出一份新的 PDF 副本。

不改 source.pdf：原文件只读进内存，在内存里克隆、加注解、序列化成 bytes 返回。
对应范围和网页上“同步到另一边”的规则一致（见 web/js/reader/sentences.js、anchor.js）：
  - 划在译文上：有句子对齐（sents）就标覆盖到的那几句英文，没有（或译文被“我的修改”改过）就标整段英文；
  - 划在原文上：标原话本身；
  - 找不到引文、对不上原页文字的，不静默丢：记进 skipped（页码、引文开头、原因）。
英文 → 原页字符：沿用 pdfwork 的字符流（extract/page-NNN.chars.json，只留 [a-z0-9] 的正规化文字 + 下标对照），
先用段首段尾锚点圈出这段在页上的范围（可跨到下一页），再逐字对齐到要标的那几句。
"""
from __future__ import annotations

import io
import re
import unicodedata
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

from .pdf import pdfwork
from .translate import sentences
from .app.i18n import tr
from .library.store import read_json

AUTHOR = "EasyRead"
# 和页面 PR.HL_COLORS / base.css 的 --hl-* 同一组颜色（pink 历史上叫粉，现在画成红）
COLORS = {"yellow": (236, 196, 92), "green": (126, 181, 118), "blue": (110, 160, 214), "pink": (226, 92, 92)}
HIGHLIGHT_TINT = 0.55  # 外观里的荧光色：和白色按这个比例混合后再用 Multiply 叠上去，黑字不会被盖住
MIN_MATCH = 0.5  # 要标的英文里，至少这么多字符在原页上对上了才写注解


class NoHighlights(ValueError):
    """这篇还没有划线（服务端回 400）。"""


# ---------- 文字正规化（带回原下标） ----------
_TEX_CMD = re.compile(r"\\[A-Za-z]+")


def _keep_quote_char(c: str) -> bool:
    """找引文用：留 ASCII 字母数字和中日文字。希腊字母等数学符号两边写法不同（\\alpha / α），都丢掉。"""
    return c.isalnum() and (c.isascii() or ord(c) >= 0x2E80)


def _quote_norm(s: str) -> tuple[str, list[int]]:
    """引文 / 段落文字 → 正规化文字和每个字符在原串里的下标。页面上看到的是渲染后的文字（无 ** 、公式已排版），
    原始数据里是标记，所以两边都只比字母数字，再去掉 TeX 命令名。"""
    out, idx = [], []
    skip = set()
    for m in _TEX_CMD.finditer(s):
        skip.update(range(m.start(), m.end()))
    for i, c in enumerate(s):
        if i in skip:
            continue
        for t in unicodedata.normalize("NFKC", c).lower():
            if _keep_quote_char(t):
                out.append(t)
                idx.append(i)
    return "".join(out), idx


def _en_norm(s: str) -> tuple[str, list[int]]:
    """英文 → 和 pdfwork._page_stream 同一套正规化（[a-z0-9]），带回原下标；公式里的 TeX 命令名不算。"""
    skip = set()
    for m in sentences._MATH.finditer(s):
        for c in _TEX_CMD.finditer(s, m.start(), m.end()):
            skip.update(range(c.start(), c.end()))
    out, idx = [], []
    for i, c in enumerate(s):
        if i in skip:
            continue
        for t in pdfwork._norm(c):
            out.append(t)
            idx.append(i)
    return "".join(out), idx


def find_quote(text: str, quote: str, prefix: str = "", suffix: str = "") -> tuple[int, int] | None:
    """和 anchor.js 的 findQuote 同一思路（原话 + 前后文打分），但在正规化文字上找。返回原串里的 [起, 止)。"""
    tn, tmap = _quote_norm(text or "")
    qn = _quote_norm(quote or "")[0]
    if not qn or not tn:
        return None
    pn, sn = _quote_norm(prefix or "")[0][-8:], _quote_norm(suffix or "")[0][:8]
    best, best_score = -1, -1
    i = tn.find(qn)
    while i >= 0:
        score = (2 if pn and tn[:i].endswith(pn) else 0) + (2 if sn and tn[i + len(qn):].startswith(sn) else 0)
        if score > best_score:
            best, best_score = i, score
        i = tn.find(qn, i + 1)
    if best < 0:
        return None
    return tmap[best], tmap[best + len(qn) - 1] + 1


# ---------- 句子对齐（和 sentences.js 的 PR.alignOf / PR.sentMd 同一套规则） ----------
def _u16_index(s: str) -> dict[int, int]:
    """UTF-16 位置 → Python 下标（只收字符边界；补充平面字符在 JS 里占 2）。"""
    pos, i = {}, 0
    for k, c in enumerate(s):
        pos[i] = k
        i += sentences.u16(c)
    pos[i] = len(s)
    return pos


def align_of(obj: dict | None) -> list | None:
    """PR.alignOf：最后一项等于两边 UTF-16 总长、两边都严格递增。对不上返回 None。"""
    s = obj.get("sents") if isinstance(obj, dict) else None
    if not isinstance(s, list) or len(s) < 2:
        return None
    en, zh = obj.get("en") or "", obj.get("zh") or ""
    last = s[-1]
    if not isinstance(last, list) or len(last) != 2 or last[0] != sentences.u16(en) or last[1] != sentences.u16(zh):
        return None
    prev = [0, 0]
    for row in s:
        if not isinstance(row, list) or len(row) != 2 or not all(isinstance(v, int) for v in row) \
                or not (row[0] > prev[0]) or not (row[1] > prev[1]):
            return None
        prev = row
    return s


_DOLLAR = re.compile(r"(?<!\\)\$")


def _balanced(t: str) -> bool:
    return t.count("**") % 2 == 0 and len(_DOLLAR.findall(t)) % 2 == 0


def _parts(text: str, s: list, col: int) -> list[tuple[int, int]] | None:
    """按 sents 的一侧把文字切成句（Python 下标）。PR.sentMd：任何一句切在 ** 粗体或公式中间，就整段不切。"""
    pos = _u16_index(text)
    out, prev = [], 0
    for row in s:
        end = pos.get(row[col])
        if end is None:
            return None  # 切在代理对中间，JS 那边也会切坏，按整段
        out.append((prev, end))
        prev = end
    if not all(_balanced(text[a:b]) for a, b in out):
        return None
    return out


# ---------- 劃線 → 要标的英文 ----------
def _obj_of(block: dict, field: str):
    """返回（英文, 译者稿, 能带 sents 的对象或 None）。"""
    if field == "caption":
        return block.get("caption_en") or "", block.get("caption_zh") or "", None
    if field == "image":
        return block.get("image_en") or "", block.get("image_zh") or "", None
    if field and field.isdigit():
        items = block.get("items") if isinstance(block.get("items"), list) else []
        it = items[int(field)] if int(field) < len(items) and isinstance(items[int(field)], dict) else {}
        return it.get("en") or "", it.get("zh") or "", (it if block.get("type") == "list" else None)
    return block.get("en") or "", block.get("zh") or "", (block if block.get("type") == "para" and not field else None)


def _block_keys(b: dict) -> list[str]:
    """同 render.js 的 PR.blockKeys。"""
    t = b.get("type")
    if t == "list":
        return [f"{b['id']}#{i}" for i in range(len(b.get("items") or []))]
    if t == "table":
        return [b["id"] + "#caption"]
    if t == "figure":
        return [b["id"] + "#caption"] + ([b["id"] + "#image"] if b.get("image_zh") or b.get("image_en") else [])
    if t in ("math", "references", "note"):
        return []
    return [b["id"]]


def target_range(note: dict, blocks: dict, edits: dict) -> dict:
    """一条划线 → {"key", "en", "start", "end", "mode"}（英文原串里的 [start, end)；mode：exact / sentence / para），
    或 {"error": 原因}。"""
    block = blocks.get(note.get("anchor"))
    if not block:
        return {"error": tr("找不到这条划线所在的段落")}
    key = note.get("key") or ""
    if not key:  # 旧划线没有 key：按页面 zhFor 的做法，取译文含这句的那一处
        keys = _block_keys(block) or [block["id"]]
        key = next((k for k in keys if note.get("quote", "") in (_obj_of(block, k.partition("#")[2])[1] or "")), keys[0])
    bid, _, field = key.partition("#")
    if bid != block.get("id"):
        block = blocks.get(bid) or block
    en, zh_agent, obj = _obj_of(block, field)
    edit = edits.get(key) if isinstance(edits.get(key), dict) and edits[key].get("zh") is not None else None
    zh_shown = edit["zh"] if edit else (zh_agent or en)
    zh_is_en = not edit and not zh_agent  # 只读原文：.zh 里排的就是英文（en-main），没有另一边
    if not en.strip():
        return {"error": tr("这处没有英文原文")}
    sides = ["en", "zh"] if note.get("side") == "en" else ["zh", "en"]
    if zh_is_en:
        sides = ["zh"]
    found = None
    for side in sides:
        text = en if side == "en" else zh_shown
        at = find_quote(text, note.get("quote", ""), note.get("prefix", ""), note.get("suffix", ""))
        if at:
            found = (side, at)
            break
    if not found:
        return {"error": tr("引文在段落里找不到")}
    side, (a, b) = found
    if side == "en" or zh_is_en:
        return {"key": key, "en": en, "start": a, "end": b, "mode": "exact", "block": block}
    s = None if edit else align_of(obj)
    zp = _parts(zh_shown, s, 1) if s else None
    ep = _parts(en, s, 0) if s else None
    if zp and ep:
        hit = [i for i, (x, y) in enumerate(zp) if x < b and a < y]
        if hit:
            start, end = ep[hit[0]][0], ep[hit[-1]][1]
            while start < end and en[start].isspace():
                start += 1
            return {"key": key, "en": en, "start": start, "end": end, "mode": "sentence", "block": block}
    return {"key": key, "en": en, "start": 0, "end": len(en), "mode": "para", "block": block}


# ---------- 英文 → 原页字符 ----------
class _Pages:
    def __init__(self, root: Path):
        self.dir = root / "extract"
        self.cache: dict[int, tuple | None] = {}

    def stream(self, n: int):
        if n not in self.cache:
            self.cache[n] = pdfwork._page_stream(self.dir, n) if n >= 1 else None
        return self.cache[n]


def _in_box(ch, box, pad=0.01) -> bool:
    cx, cy = (ch[1] + ch[3]) / 2, (ch[2] + ch[4]) / 2
    return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad


def _segment(pages: _Pages, block: dict, en: str, en_n: str, loc: dict | None):
    """这段英文在原页字符流里的范围：[(页, 起, 止)]，可能跨到下一页。找不到返回 None。"""
    head, tail = pdfwork._anchors(en)
    if not head:
        return None
    heads = [head]
    if block.get("type") == "heading" and block.get("num") and en == block.get("en"):
        heads.insert(0, pdfwork._anchors(f"{block['num']} {en}")[0])
    page = block.get("page") or (loc or {}).get("page")
    if not isinstance(page, int):
        return None
    span = len(en_n)
    for pn in (page, page + 1):
        st = pages.stream(pn)
        if not st:
            continue
        text, idx, chars = st
        hits = []
        for h in heads:
            i = text.find(h)
            while i >= 0:
                hits.append(i)
                i = text.find(h, i + 1)
            if hits:
                break
        if not hits:
            continue
        if loc and loc.get("page") == pn and loc.get("box"):  # 同一句话出现几次时，取落在定位框里的那一处
            inside = [i for i in hits if _in_box(chars[idx[i]], loc["box"])]
            hits = inside or hits
        a = hits[0]
        b = text.find(tail, a) if tail else -1
        if b >= 0:
            return [(pn, a, b + len(tail))]
        nxt = pages.stream(pn + 1)
        if nxt and tail:  # 段落接到下一页；下一页开头常先排图、边栏，段尾不一定离页首很近，整页找
            b2 = nxt[0].find(tail)
            if b2 >= 0:
                return [(pn, a, len(text)), (pn + 1, 0, b2 + len(tail))]
        end = min(len(text), a + span + 40)  # 没对到段尾：按长度估，让逐字对齐去收
        segs = [(pn, a, end)]
        rest = span - (len(text) - a)
        if rest > 0 and nxt:
            segs.append((pn + 1, 0, min(len(nxt[0]), rest + 200)))
        return segs
    return None


CORE = 8  # 逐字对齐里，连续对上这么多个字符才算可靠的锚


def _trusted(blocks) -> list:
    """SequenceMatcher 的对齐块里，短块常是和图里文字、题注、页眉的巧合（the、and…）。
    只留：可靠的长块，夹在两个长块之间的块，以及紧贴长块外侧（中间几乎没有多余字符）的短块。"""
    blocks = [m for m in blocks if m.size]
    core = [i for i, m in enumerate(blocks) if m.size >= CORE]
    if not core:
        return [max(blocks, key=lambda m: m.size)] if blocks else []
    lo, hi = core[0], core[-1]
    while lo > 0:  # 往前接：两块之间页上多出来的字不超过英文这边多出来的字 + 3
        m, n = blocks[lo - 1], blocks[lo]
        if (n.b - m.b - m.size) - (n.a - m.a - m.size) > 3:
            break
        lo -= 1
    while hi < len(blocks) - 1:
        m, n = blocks[hi], blocks[hi + 1]
        if (n.b - m.b - m.size) - (n.a - m.a - m.size) > 3:
            break
        hi += 1
    return blocks[lo:hi + 1]


def _map_range(pages: _Pages, segs, en_n: str, na: int, nb: int):
    """逐字对齐：英文正规化 [na, nb) → {页: [字符下标]}，返回 (结果, 对上的比例)。"""
    flat, where = [], []
    for pn, a, b in segs:
        text = pages.stream(pn)[0]
        flat.append(text[a:b])
        where.extend((pn, k) for k in range(a, b))
    seg_text = "".join(flat)
    sm = SequenceMatcher(None, en_n, seg_text, autojunk=False)
    pairs = []  # (英文位置, 字符流位置)
    for m in _trusted(sm.get_matching_blocks()):
        for t in range(m.size):
            if na <= m.a + t < nb:
                pairs.append((m.a + t, m.b + t))
    if nb <= na:
        return {}, 0.0
    ratio = len(pairs) / (nb - na)
    picked = set(p for _, p in pairs)
    for (a1, b1), (a2, b2) in zip(pairs, pairs[1:]):  # 两段对上的中间：页上多出来的字（公式符号）不长就补上；页眉页码这类大段不补
        if b2 - b1 > 1 and (b2 - b1) - (a2 - a1) <= 8:
            picked.update(range(b1 + 1, b2))
    out: dict[int, set] = {}
    for p in picked:
        pn, k = where[p]
        out.setdefault(pn, set()).add(pages.stream(pn)[1][k])
    return {pn: sorted(v) for pn, v in out.items()}, ratio


def _lines(chars, indices, clip: bool = True) -> list[list[float]]:
    """按原页字符顺序把选中的字符并成一行一个框（页面坐标，按页宽高归一化，左上为原点）；
    同一行里横向断开很远（跨栏）的也分开。"""
    boxes = [chars[i][1:5] for i in indices if chars[i][3] > chars[i][1] and chars[i][4] > chars[i][2]]
    if not boxes:
        return []
    widths = [b[2] - b[0] for b in boxes]
    gap = max(0.02, median(widths) * 4)
    out: list[list[float]] = []
    for b in boxes:
        if out:
            cur = out[-1]
            h = cur[3] - cur[1]
            cy = (b[1] + b[3]) / 2
            same_line = cur[1] - h * 0.1 <= cy <= cur[3] + h * 0.1
            if same_line and cur[0] - gap <= b[0] <= cur[2] + gap:
                out[-1] = [min(cur[0], b[0]), min(cur[1], b[1]), max(cur[2], b[2]), max(cur[3], b[3])]
                continue
        out.append(list(b))
    return [_clip_to_neighbours(box, chars) for box in out] if clip else out


def _clip_to_neighbours(box: list[float], chars) -> list[float]:
    """松字框比行距高，框会伸进上下相邻的行（不管那行有没有被标）：和相邻行的字框重叠的部分从中间分开，
    标示不会盖到别行的字，上下两行都标时也不会叠出一道深色。"""
    x0, y0, x1, y1 = box
    h = y1 - y0
    cy = (y0 + y1) / 2
    top, bottom = y0, y1
    for c in chars:
        if c[3] <= x0 or c[1] >= x1 or c[4] <= c[2] or not c[0].strip():
            continue
        ccy = (c[2] + c[4]) / 2
        if ccy < cy - 0.35 * h and c[4] > y0:  # 上一行伸下来
            top = max(top, (c[4] + y0) / 2)
        elif ccy > cy + 0.35 * h and c[2] < y1:  # 下一行伸上来
            bottom = min(bottom, (c[2] + y1) / 2)
    if bottom - top < h * 0.5:  # 挤得太扁（上下标、公式），宁可保留原框
        return box
    return [x0, top, x1, bottom]


# ---------- 坐标：归一化页面坐标（pdfwork._char_box 的逆运算） → PDF 用户空间 ----------
def _unrotate(x: float, y: float, rotation: int) -> tuple[float, float]:
    """渲染后（已旋转）的归一化点 → 未旋转页面上的归一化点（左上为原点）。"""
    if rotation == 90:
        return y, 1 - x
    if rotation == 180:
        return 1 - x, 1 - y
    if rotation == 270:
        return 1 - y, x
    return x, y


def to_pdf_point(x: float, y: float, bounds, rotation: int) -> tuple[float, float]:
    L, B, R, T = bounds
    ux, uy = _unrotate(x, y, rotation)
    return L + ux * (R - L), T - uy * (T - B)


def quad_of(box, bounds, rotation: int) -> list[float]:
    """一行的框 → QuadPoints 的 8 个数：按阅读方向的 左上、右上、左下、右下。"""
    x0, y0, x1, y1 = box
    pts = [to_pdf_point(x, y, bounds, rotation) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return [round(v, 3) for p in pts for v in p]


def _page_geometry(pdf: Path) -> list[tuple[tuple, int]]:
    """每页的 (可见范围 bbox, 旋转角)：和抽字时 pdfwork.extract_text 用的同一组（PDFium 的 get_bbox / get_rotation）。"""
    out = []
    with pdfwork.open_pdf(pdf) as doc:
        for i in range(len(doc)):
            with closing(doc[i]) as page:
                out.append((tuple(page.get_bbox()), int(page.get_rotation())))
    return out


# ---------- 注解对象 ----------
def _pdf_date(iso: str | None) -> str:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        d = datetime.now().astimezone()
    s = d.strftime("D:%Y%m%d%H%M%S")
    off = d.utcoffset()
    if off is None:
        return s
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{s}{sign}{mins // 60:02d}'{mins % 60:02d}'"


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


def _appearance(writer, subtype: str, quads: list[list[float]], rect: list[float], rgb: tuple[float, float, float]):
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject
    ops = []
    if subtype == "/Highlight":
        tint = tuple(1 - HIGHLIGHT_TINT * (1 - c) for c in rgb)
        ops.append("/GS0 gs " + " ".join(_fmt(c) for c in tint) + " rg")
        for q in quads:  # 所有行放进同一条路径一次填充：相邻两行的接缝不会因为抗锯齿叠出细线
            ul, ur, ll, lr = (q[0], q[1]), (q[2], q[3]), (q[4], q[5]), (q[6], q[7])
            ops.append(f"{_fmt(ul[0])} {_fmt(ul[1])} m {_fmt(ur[0])} {_fmt(ur[1])} l {_fmt(lr[0])} {_fmt(lr[1])} l {_fmt(ll[0])} {_fmt(ll[1])} l h")
        ops.append("f")
    else:
        ops.append(" ".join(_fmt(c) for c in rgb) + " RG")
        for q in quads:
            ul, ur, ll, lr = (q[0], q[1]), (q[2], q[3]), (q[4], q[5]), (q[6], q[7])
            vx, vy = ul[0] - ll[0], ul[1] - ll[1]
            h = max((vx * vx + vy * vy) ** 0.5, 1e-6)
            w = max(0.6, h * 0.07)
            off = h * 0.12 + w / 2  # 松字框的下沿在下伸部底下，往上收一点，贴近基线
            ux, uy = vx / h * off, vy / h * off
            ops.append(f"{_fmt(w)} w {_fmt(ll[0] + ux)} {_fmt(ll[1] + uy)} m {_fmt(lr[0] + ux)} {_fmt(lr[1] + uy)} l S")
    stream = DecodedStreamObject()
    stream.set_data(("q\n" + "\n".join(ops) + "\nQ\n").encode("ascii"))
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Form")
    stream[NameObject("/FormType")] = NumberObject(1)
    stream[NameObject("/BBox")] = ArrayObject([FloatObject(v) for v in rect])
    if subtype == "/Highlight":
        gs = DictionaryObject({NameObject("/Type"): NameObject("/ExtGState"), NameObject("/BM"): NameObject("/Multiply"),
                               NameObject("/CA"): FloatObject(1), NameObject("/ca"): FloatObject(1)})
        stream[NameObject("/Resources")] = DictionaryObject({NameObject("/ExtGState"): DictionaryObject({NameObject("/GS0"): gs})})
    return writer._add_object(stream)


def _annotation(writer, note: dict, quads: list[list[float]]):
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
    subtype = "/Underline" if note.get("style") == "underline" else "/Highlight"
    rgb = tuple(c / 255 for c in COLORS.get(note.get("color") or "yellow", COLORS["yellow"]))
    xs = [q[i] for q in quads for i in (0, 2, 4, 6)]
    ys = [q[i] for q in quads for i in (1, 3, 5, 7)]
    rect = [round(min(xs) - 1, 3), round(min(ys) - 1, 3), round(max(xs) + 1, 3), round(max(ys) + 1, 3)]
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject(subtype),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
        NameObject("/QuadPoints"): ArrayObject([FloatObject(v) for q in quads for v in q]),
        NameObject("/C"): ArrayObject([FloatObject(round(c, 4)) for c in rgb]),
        NameObject("/F"): NumberObject(4),  # Print
        NameObject("/T"): TextStringObject(AUTHOR),
        NameObject("/M"): TextStringObject(_pdf_date(note.get("updated") or note.get("created"))),
        NameObject("/NM"): TextStringObject(f"easyread-{note.get('id', '')}"),
    })
    body = (note.get("body") or "").strip()
    if note.get("kind") in ("question", "note") and body:
        annot[NameObject("/Contents")] = TextStringObject(body)
    annot[NameObject("/AP")] = DictionaryObject({NameObject("/N"): _appearance(writer, subtype, quads, rect, rgb)})
    return annot


# ---------- 入口 ----------
def _short(q: str, n: int = 20) -> str:
    q = " ".join((q or "").split())
    return q[:n] + ("…" if len(q) > n else "")


def plan(root: Path) -> tuple[list[dict], list[dict], int]:
    """算出每条划线要标在哪：返回（要写的 [{note, page, boxes, …}]，略过的 [{id, page, quote, reason}]，划线总数）。"""
    paper = read_json(root / "paper.json", {}) or {}
    reader = read_json(root / "reader.json", {}) or {}
    layout = read_json(root / "layout.json", {}) or {}
    blocks = {b.get("id"): b for b in paper.get("blocks", []) if isinstance(b, dict) and b.get("id")}
    edits = reader.get("edits") or {}
    notes = [n for n in (reader.get("notes") or {}).values()
             if isinstance(n, dict) and not n.get("deleted") and (n.get("quote") or "").strip()]
    notes.sort(key=lambda n: (n.get("created") or "", n.get("id") or ""))
    pages = _Pages(root)
    todo, skipped = [], []
    for note in notes:
        block = blocks.get(note.get("anchor")) or {}
        page_hint = block.get("page") or (layout.get(note.get("anchor")) or {}).get("page")

        def skip(reason, page=page_hint):
            skipped.append({"id": note.get("id"), "page": page, "quote": _short(note.get("quote")), "reason": reason})

        tgt = target_range(note, blocks, edits)
        if "error" in tgt:
            skip(tgt["error"])
            continue
        en, blk = tgt["en"], tgt["block"]
        en_n, en_idx = _en_norm(en)
        segs = _segment(pages, blk, en, en_n, layout.get(blk.get("id")))
        if not segs:
            skip(tr("原页上找不到这段英文"))
            continue
        sel = [k for k, i in enumerate(en_idx) if tgt["start"] <= i < tgt["end"]]
        if not sel:
            skip(tr("要标的英文没有字母数字"))
            continue
        chosen, ratio = _map_range(pages, segs, en_n, sel[0], sel[-1] + 1)
        if ratio < MIN_MATCH or not chosen:
            skip(tr("原页文字对不上（对上 {p}%）", p=round(ratio * 100)))
            continue
        per_page = {}
        for pn, ids in chosen.items():
            # 底线按松字框的下沿定位，不裁；荧光要裁掉伸进别行的部分
            boxes = _lines(pages.stream(pn)[2], ids, clip=note.get("style") != "underline")
            if boxes:
                per_page[pn] = boxes
        if not per_page:
            skip(tr("原页文字对不上（对上 {p}%）", p=0))
            continue
        todo.append({"note": note, "pages": per_page, "mode": tgt["mode"], "ratio": round(ratio, 3),
                     "expected": en[tgt["start"]:tgt["end"]].strip(), "key": tgt["key"]})
    return todo, skipped, len(notes)


def export(root: Path) -> tuple[bytes, dict]:
    """返回（新 PDF 的 bytes，统计）。source.pdf 只读，不写回任何文件。没有划线抛 NoHighlights。"""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject

    todo, skipped, total = plan(root)
    if not total:
        raise NoHighlights(tr("这篇还没有划线"))
    data = (root / "source.pdf").read_bytes()
    geometry = _page_geometry(root / "source.pdf")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))  # 克隆整份：书签、链接、已有注解都在
    written, items = 0, []
    for t in todo:
        quads_by_page = {}
        for pn, boxes in t["pages"].items():
            if pn > len(writer.pages) or pn > len(geometry):
                continue
            bounds, rot = geometry[pn - 1]
            quads_by_page[pn] = [quad_of(b, bounds, rot) for b in boxes]
        if not quads_by_page:
            skipped.append({"id": t["note"].get("id"), "page": min(t["pages"]), "quote": _short(t["note"].get("quote")),
                            "reason": tr("原页上找不到这段英文")})
            continue
        for pn, quads in sorted(quads_by_page.items()):
            page = writer.pages[pn - 1]
            annot = _annotation(writer, t["note"], quads)
            annot[NameObject("/P")] = page.indirect_reference
            ref = writer._add_object(annot)
            if "/Annots" not in page:
                page[NameObject("/Annots")] = ArrayObject()
            annots = page["/Annots"]
            annots = annots.get_object() if hasattr(annots, "get_object") else annots
            annots.append(ref)
        written += 1
        items.append({"id": t["note"].get("id"), "pages": sorted(quads_by_page), "mode": t["mode"], "ratio": t["ratio"],
                      "expected": t["expected"], "quads": {str(k): v for k, v in quads_by_page.items()},
                      "subtype": "Underline" if t["note"].get("style") == "underline" else "Highlight"})
    buf = io.BytesIO()
    writer.write(buf)
    skipped.sort(key=lambda s: (s.get("page") or 0, s.get("id") or ""))
    return buf.getvalue(), {"total": total, "written": written, "skipped": skipped, "items": items}


_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def filename(root: Path) -> str:
    """<论文英文标题>-划线版.pdf：去掉文件名里不能用的字符，太长就截。"""
    meta = (read_json(root / "paper.json", {}) or {}).get("meta") or {}
    title = str(meta.get("title_en") or meta.get("short_en") or meta.get("title_zh") or "paper")
    title = " ".join(_BAD_NAME.sub(" ", title).split()).strip(" .") or "paper"
    return title[:120].rstrip(" .") + tr("-划线版") + ".pdf"


def skipped_lines(stats: dict) -> list[str]:
    """给命令行和页面：一条一行“第 N 页「引文前 20 字」：原因”。"""
    return [tr("第 {page} 页「{quote}」：{reason}", page=s.get("page") or "?", quote=s.get("quote", ""), reason=s.get("reason", ""))
            for s in stats.get("skipped", [])]
