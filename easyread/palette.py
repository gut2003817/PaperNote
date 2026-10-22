"""配色偏好的严格校验。

reader.palette 形如 {"light": {"preset": "white"}, "dark": {"custom": {"bg": "#101010", "ink": "#eeeeee"}}}。
色值只收 #RRGGBB，preset 只收白名单 id，其他一律拒绝（前端只用 setProperty 套用，这里是第二道、真正的防线）。
PRESET_IDS 要和 web/js/common/palette.js 里的 PRESETS 保持一致（tests/test_palette.py 会对账）。
"""
from __future__ import annotations

import re

from .app.i18n import tr

PRESET_IDS = {
    "light": ("default", "white", "green", "bluegray", "parchment", "contrast"),
    "dark": ("default", "oled", "bluegray", "warm", "contrast"),
}
MIN_CONTRAST = 3.0  # 文字色／背景色低于它就不让存（和前端一致）
_HEX = re.compile(r"#[0-9a-fA-F]{6}")  # 用 fullmatch：$ 会放过结尾的换行


def is_hex(v) -> bool:
    return isinstance(v, str) and _HEX.fullmatch(v) is not None


def _lum(h: str) -> float:
    def ch(i):
        c = int(h[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def validate(p) -> dict:
    """返回规整后的配色；不合法就抛 ValueError（server 回 400）。None 或 {} 表示不设置。"""
    if p is None:
        return {}
    if not isinstance(p, dict) or set(p) - {"light", "dark"}:
        raise ValueError(tr("配色格式不对"))
    out = {}
    for mode, e in p.items():
        if e is None:
            continue
        if not isinstance(e, dict) or len(e) != 1:
            raise ValueError(tr("配色格式不对"))
        if "preset" in e:
            if not isinstance(e["preset"], str) or e["preset"] not in PRESET_IDS[mode]:
                raise ValueError(tr("没有这个配色"))
            out[mode] = {"preset": e["preset"]}
        elif "custom" in e:
            c = e["custom"]
            if not isinstance(c, dict) or set(c) != {"bg", "ink"} or not is_hex(c["bg"]) or not is_hex(c["ink"]):
                raise ValueError(tr("自定义配色的颜色必须是 #RRGGBB"))
            if contrast(c["bg"], c["ink"]) < MIN_CONTRAST:
                raise ValueError(tr("文字色和背景色对比度太低，看不清"))
            out[mode] = {"custom": {"bg": c["bg"].lower(), "ink": c["ink"].lower()}}
        else:
            raise ValueError(tr("配色格式不对"))
    return out
