"""界面语言：中文系统显示中文（繁体地区显示繁体），其余显示英文；设置里可以手动指定。

代码里只写（简体）中文：前端 `PR.t("中文 {n}", {n})`，后端 `tr("中文 {n}", n=…)`。
中文原文就是词条的键，英文在 web/i18n/en.json，繁体中文（台湾用语）在 web/i18n/zh-TW.json；
缺了哪条英文，tests/app/test_i18n.py 会报出来；zh-TW.json 由 scripts/gen_zhtw.py 生成，键必须和 en.json 一致。
界面语言有三种：zh（简体）、zh-TW（繁体）、en。
上游 v1.4 的繁体界面代码是 zh-Hant（词典 zh-Hant.json，繁體版已删除）；繁體版统一用 zh-TW 和 zh-TW.json，
zh-Hant 只当别名（设置、EASYREAD_LANG、系统语言里出现都按 zh-TW）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

# 不导入 config：config 间接导入了很多用 tr 的模块，这里保持没有包内依赖
EN_PATH = Path(__file__).resolve().parent.parent / "web" / "i18n" / "en.json"
ZHTW_PATH = EN_PATH.with_name("zh-TW.json")
LANGS = ("zh", "zh-TW", "en")
CHOICES = ("auto",) + LANGS
ALIASES = {"zh-Hant": "zh-TW"}  # 上游的繁体代码


def _normalize(value):
    return ALIASES.get(value, value) if isinstance(value, str) else value


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


def ui_dict(language: str) -> dict:
    """界面语言 → 词典（简体是原文，返回空词典）。"""
    language = _normalize(language)
    if language == "en":
        return en_dict()
    if language == "zh-TW":
        return zhtw_dict()
    return {}


def _is_zh(tag: str | None) -> bool:
    tag = (tag or "").strip().lower().replace("_", "-")
    return tag.startswith("zh") or tag.startswith("chinese")


def _tag_lang(tag: str | None) -> str:
    """系统语言写法 → "zh-TW"（繁体：zh-TW、zh-HK、zh-MO、zh-Hant…）、"zh"（简体，含 zh-Hans-HK）或 "en"。"""
    tag = (tag or "").strip().lower().replace("_", "-")
    if not _is_zh(tag):
        return "en"
    parts = tag.split(".")[0].split("-")
    traditional = ("hant" in parts or "traditional" in tag
                   or ("hans" not in parts and any(p in parts for p in ("tw", "hk", "mo")))
                   or (tag.startswith("chinese") and any(w in tag for w in ("taiwan", "hong kong", "macao"))))
    return "zh-TW" if traditional else "zh"


_from_tag = _tag_lang  # 旧名字


@lru_cache(maxsize=1)
def system_lang() -> str:
    # 桌面版由 Electron 传进来（macOS 从启动台打开时拿不到 LANG）
    tag = os.environ.get("EASYREAD_SYSTEM_LANG")
    if tag:
        return _tag_lang(tag)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return _tag_lang(value)
    if sys.platform == "win32":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if lid in (0x0404, 0x0C04, 0x1404):  # 台湾、香港、澳门：繁体
                return "zh-TW"
            return "zh" if lid & 0x3FF == 0x04 else "en"  # 其余中文（大陆、新加坡）简体
        except (AttributeError, OSError):
            pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3).stdout
            first = next((line.strip(' ",()') for line in out.splitlines() if line.strip(' ",()')), "")
            return _tag_lang(first)
        except (OSError, subprocess.SubprocessError):
            pass
    return "zh"  # 判断不出来时保持原来的中文


def choice() -> str:
    forced = _normalize(os.environ.get("EASYREAD_LANG"))  # 测试、排查问题时临时指定，优先于设置
    if forced in LANGS:
        return forced
    from . import prefs
    value = _normalize((prefs.load().get("ui") or {}).get("lang"))
    return value if value in CHOICES else "auto"


def lang() -> str:
    value = choice()
    return value if value in LANGS else system_lang()


def tr(text: str, **kw) -> str:
    """中文原文（简体）→ 当前语言；{name} 占位符用 kw 填。词典里没有的条目原样用简体原文，不算错误。"""
    text = ui_dict(lang()).get(text) or text
    return text.format(**kw) if kw else text


def inject(page: str, language: str | None = None) -> str:
    """返回页面时写上语言，英文、繁体中文时把词典也塞进去，前端同步就能用。"""
    language = _normalize(language)
    picked = choice() if language is None else language  # 设置里的“界面语言”要显示当前选的是哪项
    language = language or lang()
    from . import config  # 用到时再导入，见文件开头
    from ..translate import langs
    target = langs.valid(config.load().get("target"))  # 设置里的译文语言：按钮文字、没译过的论文用它
    html_lang = {"zh": "zh-CN", "zh-TW": "zh-TW"}.get(language, "en")
    page = page.replace('<html lang="zh-CN">', f'<html lang="{html_lang}" data-lang-choice="{picked}" data-target="{target}">', 1)
    if language in ("en", "zh-TW"):
        payload = json.dumps(ui_dict(language), ensure_ascii=False).replace("<", "\\u003c")
        page = page.replace("</title>", f'</title>\n<script id="pr-i18n" type="application/json">{payload}</script>', 1)
    return page
