"""界面偏好（字号、版心、主题、快捷键……）存在数据目录的 prefs.json。

以前放在浏览器 localStorage 里，换个浏览器或清一下缓存就没了；现在以这份文件为准，浏览器里只留一份缓存。
"""
from __future__ import annotations

from . import config
from .. import palette
from ..library.store import read_json, write_json_atomic

ALLOWED = {"reader", "keys", "ui", "library", "import"}  # ui：功能开关 features、快捷键总开关 keys_on


def path():
    # 测试用的临时文献库各自带一份，不碰真实偏好
    return config.library_dir() / ".prefs.json" if config.temp_library() else config.HOME / "prefs.json"


def load() -> dict:
    data = read_json(path(), {}) or {}
    r = data.get("reader")
    if isinstance(r, dict) and "palette" in r:  # 手改坏的配色不往外送（前端、离线导出都从这里读）
        try:
            r["palette"] = palette.validate(r["palette"])
        except ValueError:
            del r["palette"]
    return data


def save(patch: dict) -> dict:
    data = load()
    patch = dict(patch or {})
    r = patch.get("reader")
    if isinstance(r, dict) and "palette" in r:  # 先全部校验、再落盘：非法配色整个请求都不收
        patch["reader"] = {**r, "palette": palette.validate(r["palette"])}
    for k, v in patch.items():
        if k in ALLOWED and isinstance(v, dict):
            data[k] = {**(data.get(k) or {}), **v}
    write_json_atomic(path(), data)
    return data
