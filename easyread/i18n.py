"""界面语言：中文系统显示中文（繁体地区显示繁体），其余显示英文；设置里可以手动指定。

代码里只写（简体）中文：前端 `PR.t("中文 {n}", {n})`，后端 `tr("中文 {n}", n=…)`。
中文原文就是词条的键，英文在 web/i18n/en.json，繁体中文（台湾用语）在 web/i18n/zh-TW.json；
缺了哪条英文，tests/test_i18n.py 会报出来；zh-TW.json 由 scripts/gen_zhtw.py 生成，键必须和 en.json 一致。
界面语言有三种：zh（简体）、zh-TW（繁体）、en。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

# 不导入 config：config 间接导入了很多用 tr 的模块，这里保持没有包内依赖
EN_PATH = Path(__file__).resolve().parent / "web" / "i18n" / "en.json"
ZHTW_PATH = EN_PATH.with_name("zh-TW.json")
LANGS = ("zh", "zh-TW", "en")
CHOICES = ("auto",) + LANGS
# 这些地区/文字写法的中文用繁体（zh-TW、zh-Hant、zh-HK、zh-MO，以及 macOS 的 zh-Hant-TW 等）
_TRADITIONAL = ("zh-tw", "zh-hk", "zh-mo", "zh-hant")


@lru_cache(maxsize=2)
def _dict_cached(path: Path, mtime: float) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load(path: Path) -> dict:
    try:
        return _dict_cached(path, path.stat().st_mtime)
    except (OSError, ValueError):
        return {}


def en_dict() -> dict:
    return _load(EN_PATH)


def zhtw_dict() -> dict:
    return _load(ZHTW_PATH)


def _is_zh(tag: str | None) -> bool:
    tag = (tag or "").strip().lower().replace("_", "-")
    return tag.startswith("zh") or tag.startswith("chinese")


def _zh_variant(tag: str | None) -> str:
    """中文系统语言写法 → "zh-TW"（繁体）或 "zh"（简体）。"""
    tag = (tag or "").strip().lower().replace("_", "-")
    if tag.startswith(_TRADITIONAL) or (tag.startswith("chinese") and any(w in tag for w in ("traditional", "taiwan", "hong kong", "macao"))):
        return "zh-TW"
    return "zh"


def _from_tag(tag: str | None) -> str:
    return _zh_variant(tag) if _is_zh(tag) else "en"


@lru_cache(maxsize=1)
def system_lang() -> str:
    # 桌面版由 Electron 传进来（macOS 从启动台打开时拿不到 LANG）
    tag = os.environ.get("EASYREAD_SYSTEM_LANG")
    if tag:
        return _from_tag(tag)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return _from_tag(value)
    if sys.platform == "win32":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if lid & 0x3FF == 0x04:  # 中文；0x0404 台湾、0x0C04 香港、0x1404 澳门是繁体，其余（0x0804 大陆、0x1004 新加坡）简体
                return "zh-TW" if lid in (0x0404, 0x0C04, 0x1404) else "zh"
            return "en"
        except (AttributeError, OSError):
            pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3).stdout
            first = next((line.strip(' ",()') for line in out.splitlines() if line.strip(' ",()')), "")
            return _from_tag(first)
        except (OSError, subprocess.SubprocessError):
            pass
    return "zh"  # 判断不出来时保持原来的中文


def choice() -> str:
    forced = os.environ.get("EASYREAD_LANG")  # 测试、排查问题时临时指定，优先于设置
    if forced in LANGS:
        return forced
    from . import prefs
    value = (prefs.load().get("ui") or {}).get("lang")
    return value if value in CHOICES else "auto"


def lang() -> str:
    value = choice()
    return value if value in LANGS else system_lang()


def tr(text: str, **kw) -> str:
    """中文原文（简体）→ 当前语言；{name} 占位符用 kw 填。词典里没有的条目原样用简体原文，不算错误。"""
    current = lang()
    if current == "en":
        text = en_dict().get(text) or text
    elif current == "zh-TW":
        text = zhtw_dict().get(text) or text
    return text.format(**kw) if kw else text


def inject(page: str, language: str | None = None) -> str:
    """返回页面时写上语言，英文、繁体中文时把词典也塞进去，前端同步就能用。"""
    picked = choice() if language is None else language  # 设置里的“界面语言”要显示当前选的是哪项
    language = language or lang()
    from . import config, langs  # 用到时再导入，见文件开头
    target = langs.valid(config.load().get("target"))  # 设置里的译文语言：按钮文字、没译过的论文用它
    html_lang = {"zh": "zh-CN", "zh-TW": "zh-TW"}.get(language, "en")
    page = page.replace('<html lang="zh-CN">', f'<html lang="{html_lang}" data-lang-choice="{picked}" data-target="{target}">', 1)
    if language in ("en", "zh-TW"):
        payload = json.dumps(en_dict() if language == "en" else zhtw_dict(), ensure_ascii=False).replace("<", "\\u003c")
        page = page.replace("</title>", f'</title>\n<script id="pr-i18n" type="application/json">{payload}</script>', 1)
    return page
