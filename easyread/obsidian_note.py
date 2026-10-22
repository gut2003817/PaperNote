"""Obsidian 笔记提示词、回复解析、Markdown 组装与生成流程。"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from urllib.parse import quote

from .translate import langs
from .app.i18n import tr

_STRINGS = ("hook", "short", "problem", "method", "result", "limits")


def build_prompt(ctx: dict, engine: str, ai_images: bool = False) -> str:
    """模型只提供内容；标题、属性、划线和图片链接由程序组装。"""
    figures = [{key: fig.get(key, "") for key in ("id", "num", "page", "caption")}
               for fig in ctx.get("figures", []) if fig.get("has_box")]
    metadata = {key: ctx.get(key) for key in ("title", "authors", "year", "source")}
    metadata["marks"] = [{"n": n, "quote": _string(mark.get("quote"))[:200],
                          "page": mark.get("page"), "body": _string(mark.get("body"))}
                         for n, mark in enumerate(ctx.get("marks", []), 1)]
    instructions = """請依論文整理一篇可在 Obsidian 閱讀的繁體中文筆記。
只回一個 JSON 物件、不要任何其他文字，也不要在 JSON 外加 Markdown 程式碼圍欄。
欄位與格式如下：
- hook：30 秒版口語開場，像在台上對同學講，句子短、可直接念，約 150 字內，含一句話亮點與 2~3 個為什麼值得聽。
- short：論文簡稱，只用英數與連字號，例如 6G-SAGIN。
- tags：3~5 個主題標籤，字串陣列，不含 #。
- problem、method、result、limits：Markdown 字串，分別說明問題與動機、方法重點、結果與論文限制。hook、short 也是字串。
- figures：[{"id": "圖的 block id", "desc": "12 字以內的描述"}]。id 只能取自下方可選圖清單，只挑重要的，不限張數；沒有適合的就給空陣列。
在 problem、method、result、limits 最相關的重點段落之後，單獨一行放 {{mark:N}}（劃線編號）與 {{fig:ID}}（圖的 block id）。
每個記號最多用一次；與任何重點無關的劃線不要放，程式會另列「其他劃線」。不要複製劃線原文，也不要自己寫圖片連結。
挑了圖就請在對應重點放記號；沒有記號的圖會接在「結果」段落最後。hook（30 秒版）不放圖與劃線記號。
下方 quote 超過 200 字時已截斷，完整劃線由程式放入筆記。
- diagrams：[{"title": "示意圖標題", "mermaid": "Mermaid 語法"}]。mermaid 只放 Mermaid 語法本身，不含三個反引號圍欄；沒有適合的就給空陣列。
內容只能來自論文；讀者劃線與筆記只用來辨識關注點，不可當作論文證據。
不要編造數據或引用，推論要標「（推論）」，保留論文原有的確定程度。不要寫「我的想法」。
段落不要重複論文標題、作者或來源，不使用一級標題，也不要產生圖片連結。
"""
    if ai_images:
        instructions += """- ai_images：[{"kind": "cover 或 explain", "desc": "12 字以內中文描述", "prompt": "英文畫面描述"}]。
恰好 1 張 cover：整篇核心概念的封面概念圖，讓聽眾一眼看懂；0~3 張 explain：只圖解真的難懂的概念。
prompt 請依論文內容決定畫風（扁平插畫、資訊圖表風、示意圖等），用英文描述具體構圖與元素。
圖中不得有任何文字、字母、數字、標誌；只畫論文確實提出的概念，不畫不存在的數據結果。
explain 用 {{img:N}} 記號放在 problem、method、result、limits 的相關重點段落之後，單獨一行。
N 是 explain 在陣列中的 1 起算序號，只算 explain、不算 cover；每個記號最多一次。cover 不用記號。
"""  # i18n-ok 提示词
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
    return "\n".join(line for line in _clean(_string(value)).splitlines()
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
    visuals = [dict(kind=image["kind"], desc=_string(image.get("desc")), prompt=image["prompt"][:1500])
               for image in _list(data.get("ai_images"))
               if isinstance(image, dict) and image.get("kind") in ("cover", "explain")
               and isinstance(image.get("prompt"), str) and image["prompt"].strip()]
    out["ai_images"] = ([image for image in visuals if image["kind"] == "cover"][:1]
                        + [image for image in visuals if image["kind"] == "explain"][:3])
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


def _clean(value) -> str:
    # 保留换行与 tab，移除 YAML 禁止的控制字元及无法编码的代理字元。
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff]", "",
                  "" if value is None else str(value))


def _yaml(value) -> str:
    # JSON 双引号字串也是合法 YAML，统一处理反斜线、引号及换行。
    return json.dumps(_clean(value), ensure_ascii=False)


def _inline(value) -> str:
    text = " ".join(_clean(value).splitlines()).strip()
    return text + "".join(" " + token for token in _unclosed(text))


_FENCE_OPEN = re.compile(r"^((?: {0,3}> ?)* {0,3})(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^((?: {0,3}> ?)* {0,3})(`{3,}|~{3,}) *$")
# 一级标题可能藏在引用、列表里（> # x、- # x、1. # x），同样降级
_CONTAINER = r"(?: *(?:> ?|[-*+] +|[0-9]{1,9}[.)] +))*"
_H1 = re.compile(r"^(" + _CONTAINER + r" *)#(?: +|$)")
_SETEXT = re.compile(r"^(" + _CONTAINER + r" *)=+ *$")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)")


def _unclosed(value: str) -> list[str]:
    visible = "\n\n".join(_CODE_SPAN.sub("", block) for block in re.split(r"\n *\n", value))
    return [token for token in ("%%", "$$") if visible.count(token) % 2]


def _markdown(value: str, transform: Callable[[str], str] | None = None) -> str:
    # 模型即使忽略提示词，也不能再增加笔记的一层标题；程式码保持原样。
    lines, outside, fence = [], [], None
    list_indent = 0
    for line in _clean(value).splitlines():
        line = line.expandtabs(4)
        # 清单续行的缩排属于容器，不能误当成四格缩排程式码。
        quote_prefix = re.match(r"^(?: {0,3}> ?)*", line)[0]
        content = line[len(quote_prefix):]
        item = re.match(r"^ {0,3}(?:[-*+]|[0-9]{1,9}[.)]) +", content)
        # 容器结束会自动结束其内的围栏；退回外层后须重新判断当前行。
        if fence is not None and (
                quote_prefix.count(">") < prefix.count(">")
                or (list_indent and content.strip() and not content.startswith(" " * list_indent))):
            fence = None
            list_indent = 0
        if fence is None:
            if item:
                list_indent = len(item[0])
            elif content.strip() and not content.startswith(" " * list_indent):
                list_indent = 0
        candidate = line
        if list_indent and content.startswith(" " * list_indent):
            candidate = quote_prefix + content[list_indent:]
        if fence is not None:
            lines.append(line)
            close = _FENCE_CLOSE.match(candidate)
            if (close and close[1].count(">") == prefix.count(">")
                    and close[2][0] == fence[0] and len(close[2]) >= len(fence)):
                fence = None
            continue
        opened = _FENCE_OPEN.match(candidate)
        # CommonMark：反引号围栏的 info string 不能含反引号，否则不是围栏
        if opened and not (opened[2][0] == "`" and "`" in opened[3]):
            prefix, fence = line[:line.index(opened[2])], opened[2]
            lines.append(line)
            outside.append("\n\n")  # 行内程式码不会跨越围栏区块
            continue
        line = re.sub(r"^( {0,3})<", r"\1&lt;", line)
        # 行中注解也可能隐藏下一行的闭合记号。
        line = line.replace("<!--", "&lt;!--")
        line = _H1.sub(r"\1### ", line)
        # Setext 一级标题降为二级，保留引用及列表前缀。
        line = _SETEXT.sub(r"\1---", line)
        outside.append("" if content.startswith(" " * (list_indent + 4)) else line)
        lines.append(transform(line) if transform is not None else line)
    if fence is not None:  # 模型没闭合围栏：补上，免得吞掉后面所有段落
        lines.append(prefix + fence)
    # 只统计围栏与配对的行内程式码之外的 Obsidian 注解／数学记号。
    lines.extend(_unclosed("\n".join(outside)))
    return "\n".join(lines).strip("\n")


def render(ctx: dict, data: dict, fig_files: dict[str, str], today: str | None = None,
           ai_files: dict[str, str] | None = None) -> str:
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
    figures = {fig["id"]: fig for fig in ctx.get("figures", [])}
    images = {}
    for selected in normalized["figures"]:
        id_ = selected["id"]
        if id_ not in figures or id_ not in fig_files or id_ in images:
            continue
        fig = figures[id_]
        num, page, desc = _inline(fig.get("num")), _inline(fig.get("page")), _inline(selected["desc"])
        alt = re.sub(r"([\\\[\]])", r"\\\1", f"圖{num} {desc}")  # i18n-ok 固定繁体笔记格式
        images[id_] = f"![{alt}](附圖/{quote(_clean(fig_files[id_]), safe='')})\n圖{num}：{desc}（第 {page} 頁）"  # i18n-ok 固定繁体笔记格式
    marks = []
    for mark in ctx.get("marks", []):
        # 原句与多行笔记均留在同一个引用内，防止页码或笔记变成外部段落。
        entry = _markdown(_string(mark.get("quote")))
        if mark.get("page") is not None:
            entry += f"\n（第 {_inline(mark['page'])} 頁）"  # i18n-ok 固定繁体笔记格式
        if _string(mark.get("body")).strip():
            body = _markdown(mark["body"])
            # 围栏必须独占一行；前置「笔记：」会使开围栏变成普通文字。
            separator = "\n" if _FENCE_OPEN.match(body.split("\n", 1)[0]) else ""
            entry += "\n筆記：" + separator + body  # i18n-ok 固定繁体笔记格式
        marks.append("\n".join("> " + line for line in entry.splitlines()))

    ai_blocks, explains = {}, []
    for visual in normalized["ai_images"]:
        if visual["kind"] == "cover":
            key = "cover"
        else:
            explains.append(visual)
            key = f"explain-{len(explains)}"
        if key not in (ai_files or {}):
            continue
        desc = _inline(visual["desc"]).replace("<!--", "&lt;!--")
        alt = re.sub(r"([\\\[\]])", r"\\\1", f"示意圖（AI 生成） {desc}")  # i18n-ok 固定繁体笔记格式
        ai_blocks[key] = f"![{alt}](附圖/{quote(_clean(ai_files[key]), safe='')})\n示意圖（AI 生成）：{desc}"  # i18n-ok 固定繁体笔记格式

    seen_figures, seen_marks, seen_ai = set(), set(), set()

    def expand(match: re.Match) -> str:
        kind, id_ = match.groups()
        if kind == "fig":
            if id_ not in images or id_ in seen_figures:
                return ""
            seen_figures.add(id_)
            block = images[id_]
        elif kind == "img":
            number = id_.lstrip("0")
            if not re.fullmatch(r"[0-9]+", id_) or not number or len(number) > len(str(len(explains))):
                return ""
            n = int(number)
            key = f"explain-{n}"
            if n > len(explains) or key not in ai_blocks or key in seen_ai:
                return ""
            seen_ai.add(key)
            block = ai_blocks[key]
        else:
            # 先检查文本，避免恶意超长整数触发 int 的转换限制。
            number = id_.lstrip("0")
            if not re.fullmatch(r"[0-9]+", id_) or not number or len(number) > len(str(len(marks))):
                return ""
            n = int(number)
            if n > len(marks) or n in seen_marks:
                return ""
            seen_marks.add(n)
            block = marks[n - 1]
        return "\n\n" + block + "\n\n"

    def placed(value: str) -> str:
        # 复用围栏追踪：先规范 Markdown，再仅在围栏外展开记号。
        # 再规范一次，防止删除/展开行中记号后露出新的标题或未闭合围栏。
        value = _markdown(_markdown(value), lambda line: re.sub(r"\{\{(fig|mark|img):([^{}]*)\}\}", expand, line))
        return re.sub(r"\n{3,}", "\n\n", _markdown(value))

    sections = {key: placed(normalized[key]) for key in ("problem", "method", "result", "limits")}
    for heading, key in (("30 秒版", "hook"), ("問題與動機", "problem"), ("方法重點", "method")):  # i18n-ok 固定繁体笔记格式
        text = _markdown(normalized[key]) if key == "hook" else sections[key]
        if key == "hook" and "{{img:" in text:
            # 删除记号可能露出标题或围栏，和正文一样再规范一次。
            text = _markdown(_markdown(text, lambda line: re.sub(r"\{\{img:[^{}]*\}\}", "", line)))
        if key == "hook" and "cover" in ai_blocks:
            text += "\n\n" + ai_blocks["cover"]
        if key == "method":
            text += "".join("\n\n" + ai_blocks[f"explain-{n}"] for n in range(1, len(explains) + 1)
                            if f"explain-{n}" in ai_blocks and f"explain-{n}" not in seen_ai)
        parts.append("## " + heading + "\n\n" + text)
    for diagram in normalized["diagrams"]:
        if diagram["mermaid"]:
            parts.append("**" + _inline(diagram["title"]) + "**\n\n```mermaid\n" + _clean(diagram["mermaid"]) + "\n```")
    result = [sections["result"]] + [image for id_, image in images.items() if id_ not in seen_figures]
    parts.append("## 結果\n\n" + "\n\n".join(result))  # i18n-ok 固定繁体笔记格式
    other_marks = [mark for n, mark in enumerate(marks, 1) if n not in seen_marks]
    if other_marks:
        parts.append("## 其他劃線\n\n" + "\n\n".join(other_marks))  # i18n-ok 固定繁体笔记格式
    limits = sections["limits"] or "（論文沒有明確討論限制）"  # i18n-ok 固定繁体笔记格式
    parts.append("## 限制與我的想法\n\n" + limits + "\n\n### 我的想法")  # i18n-ok 固定繁体笔记格式
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)) + "\n\n"


def generate(ws, cfg: dict, cancel=None, model: str | None = None,
             ai_images: bool = False, progress=None) -> dict:
    """先完成模型调用与解析，再新增笔记及附图，绝不覆盖已有文件。"""
    # chat_models → engines → config 有初始化依赖，调用时再载入。
    from . import obsidian_aiimg, obsidian_context, obsidian_figures, obsidian_vault
    from .chat import chat_models
    from .engines import engines

    path = cfg.get("obsidian_vault", "")
    if not path:
        raise ValueError(tr("尚未设置 Obsidian 文件夹"))
    vault = obsidian_vault.check_vault(path)
    ctx = obsidian_context.collect(ws)
    ecfg, _ = chat_models.engine_cfg(cfg, model)
    prompt = build_prompt(ctx, ecfg["engine"], ai_images=ai_images)
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
    ai_files, ai_skipped, ai_error = {}, 0, ""
    if ai_images and data["ai_images"]:
        codex_cfg = cfg.get("codex") or {}
        explain_n = 0
        total = len(data["ai_images"])
        # 逐张生成便于取消及回报进度；任何生图错误都不能阻断笔记。
        try:
            available = engines.codex_path(codex_cfg)
            if not available:
                ai_error = tr("找不到 Codex 命令：{cmd}（先装好并登录 Codex CLI）",
                              cmd=codex_cfg.get("command") or "codex")[:200]
        except Exception as exc:  # noqa: BLE001
            available, ai_error = False, str(exc)[:200]
        if progress is not None and available:
            progress(0, total)  # 第一张约一分钟，先让前端知道已进入生图
        for done, visual in enumerate(data["ai_images"], 1):
            if visual["kind"] == "cover":
                key, image_stem = "cover", f"{short}-AI-封面"  # i18n-ok 固定繁体笔记格式
            else:
                explain_n += 1
                key = f"explain-{explain_n}"
                image_stem = f"{short}-AI-示意{explain_n}-{visual['desc']}"  # i18n-ok 固定繁体笔记格式
            try:
                if not available:
                    ai_skipped += 1
                else:
                    ai_files[key] = obsidian_aiimg.generate_image(
                        codex_cfg, visual["prompt"], attach_dir,
                        obsidian_vault.safe_name(image_stem), cancel=cancel)
            except Exception as exc:  # noqa: BLE001 失败、逾时或取消都只略过这张图
                ai_skipped += 1
                if not ai_error:
                    ai_error = str(exc)[:200] or type(exc).__name__
            if progress is not None:
                progress(done, total)
    md = render(ctx, data, fig_files, ai_files=ai_files)
    stem = obsidian_vault.safe_name(short)
    if (notes_dir / f"{stem}.md").exists():
        stem = f"{stem}-{obsidian_vault.stamp()}"
    path = obsidian_vault.write_new(notes_dir, stem, ".md", md.encode("utf-8"))
    return {"path": str(path), "figures": len(fig_files),
            "diagrams": sum(bool(diagram["mermaid"]) for diagram in data["diagrams"]),
            "skipped": skipped, "ai_images": len(ai_files),
            "ai_skipped": ai_skipped, "ai_error": ai_error}
