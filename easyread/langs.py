"""译文语言：论文翻成哪种语言。默认中文；设置里可以改，每篇论文第一次翻译时记下当时的语言。

数据格式不变：译文仍然存在 zh / caption_zh / title_zh 这些字段里，字段名只是历史叫法。
"""
from __future__ import annotations

# 代码 → (界面上显示的名字, 提示词里怎么称呼, 英文名)
TARGETS = {
    "zh": ("中文", "中文", "Chinese"),  # i18n-ok 语言名
    "zh-TW": ("繁體中文", "繁體中文（台灣用語）", "Traditional Chinese"),  # i18n-ok 语言名；字段仍叫 zh/title_zh，里面写繁体
    "ja": ("日本語", "日语（日本語）", "Japanese"),  # i18n-ok
    "ko": ("한국어", "韩语（한국어）", "Korean"),  # i18n-ok
    "es": ("Español", "西班牙语（Español）", "Spanish"),  # i18n-ok
    "fr": ("Français", "法语（Français）", "French"),  # i18n-ok
    "de": ("Deutsch", "德语（Deutsch）", "German"),  # i18n-ok
}
DEFAULT = "zh"


def valid(code: str | None) -> str:
    return code if code in TARGETS else DEFAULT


def of_paper(meta: dict | None, cfg: dict | None = None) -> str:
    """这篇论文的译文语言：翻过的用当时记下的，没翻过的用设置里的。"""
    meta = meta or {}
    if meta.get("target") in TARGETS:
        return meta["target"]
    if meta.get("title_zh"):  # 1.3 以前译的论文没记语言，都是中文
        return DEFAULT
    if cfg is None:
        from . import config
        cfg = config.load()
    return valid(cfg.get("target"))


def remember(ws, code: str | None) -> None:
    """导入时选了译文语言：记到这篇论文上。已经有译文的论文不改，免得一篇里混两种语言。"""
    if code not in TARGETS:
        return

    def apply(paper):
        meta = paper.setdefault("meta", {})
        if not meta.get("target") and not any(b.get("zh") or b.get("caption_zh") for b in paper.get("blocks", [])):
            meta["target"] = code
    ws.update("paper", apply)


def prompt_name(code: str) -> str:
    return TARGETS[valid(code)][1]


def is_chinese(code: str | None) -> bool:
    """译成中文（简体或繁体）：中文专属的提示词规则对两者都适用。"""
    return code in ("zh", "zh-TW")


# 译成/回答成繁体中文时加给模型的要求（翻译、问 AI、整理笔记共用）
TW_STYLE = ("输出繁體中文，用台灣慣用詞與術語（軟體、檔案、資料夾、設定、資訊、網路、伺服器、程式、資料庫、演算法、品質、預設、匯入／匯出……），"  # i18n-ok 提示词
            "不要出现簡體字，也不要用大陸用語（軟件、文件、信息、網絡、默認、質量）；"  # i18n-ok 提示词
            "標點用全形「，。、：；？！」，引號用「」（內層用『』），不用 “” 和 ‘’；數字、單位、公式、程式碼、引用號 [n] 照原樣。")  # i18n-ok 提示词


def reply_note(meta: dict | None) -> str:
    """回答语言是繁体中文时，提示词里要多加的一句；其他语言返回空串。"""
    return TW_STYLE + "\n" if reply_lang(meta) == prompt_name("zh-TW") else ""


def listing() -> list[dict]:
    return [{"id": k, "name": v[0]} for k, v in TARGETS.items()]


def reply_lang(meta: dict | None) -> str:
    """问 AI、整理笔记用什么语言回答：论文翻过就用译文语言，没翻过跟界面语言。提示词里的称呼。"""
    meta = meta or {}
    if meta.get("target") in TARGETS:
        return prompt_name(meta["target"])
    if meta.get("title_zh"):  # 1.3 以前译的论文没记语言，都是中文
        return "中文"  # i18n-ok 提示词
    from . import i18n
    ui = i18n.lang()
    if ui == "zh-TW":  # 没翻过的论文，繁体界面下用繁体回答
        return prompt_name("zh-TW")
    return "中文" if ui == "zh" else "英文（English）"  # i18n-ok 提示词
