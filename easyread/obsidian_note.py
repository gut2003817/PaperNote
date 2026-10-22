"""Obsidian 笔记提示词、回复解析、Markdown 组装与生成流程。"""
from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import quote

from . import langs
from .i18n import tr

_STRINGS = ("hook", "short", "problem", "method", "result", "limits")


def build_prompt(ctx: dict, engine: str) -> str:
    """模型只提供内容；标题、属性、划线和图片链接由程序组装。"""
    figures = [{key: fig.get(key, "") for key in ("id", "num", "page", "caption")}
               for fig in ctx.get("figures", []) if fig.get("has_box")]
    metadata = {key: ctx.get(key) for key in ("title", "authors", "year", "source", "marks")}
    instructions = """請依論文整理一篇可在 Obsidian 閱讀的繁體中文筆記。
只回一個 JSON 物件、不要任何其他文字，也不要在 JSON 外加 Markdown 程式碼圍欄。
欄位與格式如下：
- hook：30 秒版口語開場，像在台上對同學講，句子短、可直接念，約 150 字內，含一句話亮點與 2~3 個為什麼值得聽。
- short：論文簡稱，只用英數與連字號，例如 6G-SAGIN。
- tags：3~5 個主題標籤，字串陣列，不含 #。
- problem、method、result、limits：Markdown 字串，分別說明問題與動機、方法重點、結果與論文限制。hook、short 也是字串。
- figures：[{"id": "圖的 block id", "desc": "12 字以內的描述"}]。id 只能取自下方可選圖清單，只挑重要的，不限張數；沒有適合的就給空陣列。
- diagrams：[{"title": "示意圖標題", "mermaid": "Mermaid 語法"}]。mermaid 只放 Mermaid 語法本身，不含三個反引號圍欄；沒有適合的就給空陣列。
內容只能來自論文；讀者劃線與筆記只用來辨識關注點，不可當作論文證據。
不要編造數據或引用，推論要標「（推論）」，保留論文原有的確定程度。不要寫「我的想法」。
段落不要重複論文標題、作者或來源，不使用一級標題，也不要產生圖片連結。
"""
    # 提示词与固定的繁体笔记格式不是界面词条。
    source = ("論文在當前目錄的 paper.json，請用 Read 讀取原文。" if engine == "claude"  # i18n-ok 提示词
              else "論文內容：\n" + str(ctx.get("text") or ""))  # i18n-ok 提示词
    return "\n\n".join((langs.TW_STYLE, langs.NOTE_STYLE, instructions,
                          "論文資訊與讀者劃線：\n" + json.dumps(metadata, ensure_ascii=False),  # i18n-ok 提示词
                          "可選圖清單：\n" + json.dumps(figures, ensure_ascii=False), source))  # i18n-ok 提示词


def _string(value) -> str:
    return value if isinstance(value, str) else ""


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _mermaid(value) -> str:
    # 有些模型把围栏又放进 JSON 字串，删除整条围栏行。
    return "\n".join(line for line in _string(value).splitlines()
                     if not line.lstrip().startswith("```")).strip()


def _normalize(data: dict) -> dict:
    out = {key: _string(data.get(key)) for key in _STRINGS}
    tags = [re.sub(r"[#\s]+", "", tag) for tag in _list(data.get("tags")) if isinstance(tag, str)]
    out["tags"] = list(dict.fromkeys(tag for tag in tags if tag))
    out["figures"] = [{"id": fig["id"], "desc": _string(fig.get("desc"))}
                      for fig in _list(data.get("figures"))
                      if isinstance(fig, dict) and isinstance(fig.get("id"), str) and fig["id"]]
    out["diagrams"] = [{"title": _string(diagram.get("title")), "mermaid": _mermaid(diagram.get("mermaid"))}
                       for diagram in _list(data.get("diagrams")) if isinstance(diagram, dict)]
    return out


def parse_reply(text: str) -> dict:
    """逐个检查平衡的大括号，跳过废话内的非法对象，尊重 JSON 字串跳脱。"""
    start, depth, in_string, escaped = None, 0, False, False
    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start, depth = index, 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return _normalize(json.loads(text[start:index + 1]))
                except json.JSONDecodeError:
                    start = None
    raise ValueError(tr("模型回复不是有效的 JSON"))


def _yaml(value) -> str:
    # JSON 双引号字串也是合法 YAML，统一处理反斜线、引号及换行。
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def _inline(value) -> str:
    return " ".join(str(value or "").splitlines()).strip()


_FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*$")
# 一级标题可能藏在引用、列表里（> # x、- # x、1. # x），同样降级
_H1 = re.compile(r"^((?:\s{0,3}(?:>[ \t]?|[-*+][ \t]+|\d{1,9}[.)][ \t]+))*)\s{0,3}#(?:[ \t]+|$)")


def _markdown(value: str) -> str:
    # 模型即使忽略提示词，也不能再增加笔记的一层标题；程式码保持原样。
    lines, fence = [], None
    for line in value.splitlines():
        if fence is not None:
            lines.append(line)
            close = _FENCE_CLOSE.match(line)
            if close and close[1][0] == fence[0] and len(close[1]) >= len(fence):
                fence = None
            continue
        opened = _FENCE_OPEN.match(line)
        # CommonMark：反引号围栏的 info string 不能含反引号，否则不是围栏
        if opened and not (opened[1][0] == "`" and "`" in opened[2]):
            fence = opened[1]
            lines.append(line)
            continue
        line = _H1.sub(r"\1### ", line)
        # Setext 一级标题降为二级，避免 Obsidian 识别为额外 H1。
        line = re.sub(r"^\s{0,3}=+\s*$", "---", line)
        lines.append(line)
    if fence is not None:  # 模型没闭合围栏：补上，免得吞掉后面所有段落
        lines.append(fence)
    return "\n".join(lines).strip()


def render(ctx: dict, data: dict, fig_files: dict[str, str], today: str | None = None) -> str:
    """固定繁体笔记结构；未知或未导出的图静默略过，不产生坏链接。"""
    # 保留调用者提供的标签原文（解析回复时才清理），不改写输入。
    tags = _list(data.get("tags"))
    authors = _list(ctx.get("authors"))
    lines = ["---"]
    for key, values in (("tags", tags), ("authors", authors)):
        lines.append(f"{key}:" if values else f"{key}: []")
        lines.extend("  - " + _yaml(value) for value in values)
        if key == "tags":
            lines.append("year: " + _yaml(ctx.get("year")))
    lines.extend(("source: " + _yaml(ctx.get("source")),
                  "created: " + _yaml(today if today is not None else date.today().isoformat()), "---"))
    title = _inline(ctx.get("title")) or _inline(data.get("short")) or "未命名論文"  # i18n-ok 固定繁体笔记格式
    parts = ["\n".join(lines), "# " + title]
    normalized = _normalize(data)
    for heading, key in (("30 秒版", "hook"), ("問題與動機", "problem"), ("方法重點", "method")):  # i18n-ok 固定繁体笔记格式
        parts.append("## " + heading + "\n\n" + _markdown(normalized[key]))
    for diagram in normalized["diagrams"]:
        if diagram["mermaid"]:
            parts.append("**" + _inline(diagram["title"]) + "**\n\n```mermaid\n" + diagram["mermaid"] + "\n```")
    parts.append("## 結果\n\n" + _markdown(normalized["result"]))  # i18n-ok 固定繁体笔记格式
    figures = {fig["id"]: fig for fig in ctx.get("figures", [])}
    images, seen = [], set()
    for selected in normalized["figures"]:
        id_ = selected["id"]
        if id_ not in figures or id_ not in fig_files or id_ in seen:
            continue
        seen.add(id_)
        fig = figures[id_]
        num, page, desc = _inline(fig.get("num")), _inline(fig.get("page")), _inline(selected["desc"])
        alt = re.sub(r"([\\\[\]])", r"\\\1", f"圖{num} {desc}")  # i18n-ok 固定繁体笔记格式
        images.append(f"![{alt}](附圖/{quote(fig_files[id_], safe='')})\n圖{num}：{desc}（第 {page} 頁）")  # i18n-ok 固定繁体笔记格式
    if images:
        parts.append("## 重要圖表\n\n" + "\n\n".join(images))  # i18n-ok 固定繁体笔记格式
    marks = []
    for mark in ctx.get("marks", []):
        entry = "\n".join("> " + line for line in _string(mark.get("quote")).splitlines())
        if mark.get("page") is not None:
            entry += f"\n（第 {_inline(mark['page'])} 頁）"  # i18n-ok 固定繁体笔记格式
        if _string(mark.get("body")).strip():
            entry += "\n筆記：" + _markdown(mark["body"])  # i18n-ok 固定繁体笔记格式
        marks.append(entry)
    parts.append("## 我的劃線\n\n" + ("\n\n".join(marks) if marks else "（本篇沒有劃線）"))  # i18n-ok 固定繁体笔记格式
    limits = _markdown(normalized["limits"]) or "（論文沒有明確討論限制）"  # i18n-ok 固定繁体笔记格式
    parts.append("## 限制與我的想法\n\n" + limits + "\n\n### 我的想法")  # i18n-ok 固定繁体笔记格式
    return "\n\n".join(parts) + "\n\n"


def generate(ws, cfg: dict, cancel=None, model: str | None = None) -> dict:
    """先完成模型调用与解析，再新增笔记及附图，绝不覆盖已有文件。"""
    # chat_models → engines → config 有初始化依赖，调用时再载入。
    from . import chat_models, engines, obsidian_context, obsidian_figures, obsidian_vault

    path = cfg.get("obsidian_vault", "")
    if not path:
        raise ValueError(tr("尚未设置 Obsidian 文件夹"))
    vault = obsidian_vault.check_vault(path)
    ctx = obsidian_context.collect(ws)
    ecfg, _ = chat_models.engine_cfg(cfg, model)
    prompt = build_prompt(ctx, ecfg["engine"])
    text = engines.run(ecfg, prompt, ws.root, cancel=cancel)
    data = parse_reply(text)

    # 在解析成功之前不建立 vault 子目录、不留下任何产物。
    notes_dir, attach_dir = obsidian_vault.note_dirs(vault)
    figures = {fig["id"]: fig for fig in ctx["figures"]}
    blocks = {block["id"]: block for block in (ws.load("paper") or {}).get("blocks", [])
              if "id" in block}
    short = data["short"] or ctx["title"]
    fig_files, seen, skipped = {}, set(), 0
    for selected in data["figures"]:
        id_ = selected["id"]
        if id_ in seen:
            continue
        seen.add(id_)
        if not figures.get(id_, {}).get("has_box") or id_ not in blocks:
            skipped += 1
            continue
        try:
            fig_files[id_] = obsidian_figures.export_figure(
                ws, blocks[id_], short, selected["desc"], attach_dir)
        except Exception:  # noqa: BLE001 单张截图失败不阻断整篇笔记，包括 PDFium 错误
            skipped += 1
    md = render(ctx, data, fig_files)
    stem = obsidian_vault.safe_name(short)
    if (notes_dir / f"{stem}.md").exists():
        stem = f"{stem}-{obsidian_vault.stamp()}"
    path = obsidian_vault.write_new(notes_dir, stem, ".md", md.encode("utf-8"))
    return {"path": str(path), "figures": len(fig_files),
            "diagrams": sum(bool(diagram["mermaid"]) for diagram in data["diagrams"]),
            "skipped": skipped}
