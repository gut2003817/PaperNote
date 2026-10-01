"""組 prompt、呼叫 AI、驗證輸出。AI 的輸出一律先過 schema 才能進筆記。"""
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from . import ai_runner
from .ai_runner import AIError
from .pdf_service import FigureInfo
from .schema import BlockList, flatten

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary_md": {"type": "string"}},
    "required": ["summary_md"],
    "additionalProperties": False,
}
BLOCKS_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "blocks_json": {"type": "string"}},
    "required": ["reply", "blocks_json"],
    "additionalProperties": False,
}

BLOCK_FORMAT_GUIDE = """\
blocks_json 必須是一個「JSON 陣列」的字串。每個元素是下列其中一種區塊（不要加 id，系統會自動產生）：
- {"type":"heading","level":1|2|3,"text":"..."}
- {"type":"paragraph","text":"..."}   text 可用 **粗體**、*斜體*、`程式碼`、[連結](網址)
- {"type":"eli5","text":"..."}   白話解釋框
- {"type":"chart","spec":{Vega-Lite v5 規格，資料寫在 data.values},"source":"出處，例如 Table 2, p.7"}
- {"type":"diagram","mermaid":"Mermaid 原始碼，例如 flowchart LR\\n  A[輸入] --> B[模型]"}
- {"type":"figure","path":"圖檔名（只能用圖片清單中的檔名）","caption":"說明","page":頁碼}
- {"type":"columns","columns":[{"widthPct":50,"blocks":[...]},{"widthPct":50,"blocks":[...]}]}
  2–3 欄並排，widthPct 總和 100；欄內不可再放 columns。
規則：chart 的數字必須直接來自論文並寫明 source；找不到確切數字就不要畫 chart。
"""

ELI5_GUIDE = """\
eli5 區塊的寫法：讀者是沒讀過這篇論文的大學部同學。用一個生活化的比喻開頭，避免術語；
非用不可的術語當場用一句話解釋；3–5 句。（若你有 eli5 skill 可用，請使用它。）
"""


class AIFormatError(AIError):
    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


@dataclass
class EditResult:
    reply: str
    replace: list | None


def generate_summary(engine, paper_dir: Path, run=ai_runner.run) -> str:
    prompt = (
        "請閱讀目前資料夾中的 paper.pdf，寫一份給後續整理用的重點摘要（Markdown、繁體中文、800–1500 字）。\n"
        "包含：研究問題與動機、方法核心、實驗設定（資料集、比較對象、指標）、"
        "主要結果（附數字與表格／圖編號、頁碼）、限制。數字一律照原文並標註出處（例如 Table 2, p.7）。\n"
        '以 JSON 回傳：{"summary_md": "..."}'
    )
    out = run(engine, prompt, SUMMARY_SCHEMA, paper_dir)
    summary = out.get("summary_md")
    if not isinstance(summary, str) or len(summary.strip()) < 50:
        raise AIFormatError("AI 產生的摘要過短或缺失", json.dumps(out, ensure_ascii=False))
    return summary


def _figure_list(figures: list[FigureInfo]) -> str:
    kinds = {"embedded": "嵌入圖片", "page": "整頁截圖"}
    return "\n".join(f"- {f.file}（第 {f.page} 頁，{kinds[f.kind]}）" for f in figures) or "（無）"


def generate_note(engine, paper_dir: Path, summary: str, figures: list[FigureInfo],
                  run=ai_runner.run) -> list:
    prompt = f"""你要幫一位研究生準備課堂 paper presentation 的筆記。資料夾中有 paper.pdf，以下是已整理的摘要：
<summary>
{summary}
</summary>
可用的圖片清單：
{_figure_list(figures)}

請產生筆記區塊。第一個區塊是 level 1 heading（論文標題）。接著依序包含這些段落，各以 level 2 heading 開頭：
研究動機與問題、方法、實驗設定、結果、限制、討論問題。
每個段落至少一個 eli5 區塊。方法段落放一張 diagram；結果段落盡量放 chart；需要原圖時用 figure。
{ELI5_GUIDE}
{BLOCK_FORMAT_GUIDE}
以 JSON 回傳：{{"reply": "一句話說明你做了什麼", "blocks_json": "..."}}"""
    _, blocks = _call_blocks(engine, prompt, paper_dir, run, {f.file for f in figures},
                             allow_empty=False)
    return blocks


def _dump(x) -> str:
    return "（無）" if x is None else json.dumps(x, ensure_ascii=False)


def edit_selection(engine, paper_dir: Path, summary: str, selected: list[dict], selected_text: str,
                   before: dict | None, after: dict | None, message: str, figures: list[str],
                   allow_columns: bool = True, run=ai_runner.run) -> EditResult:
    text_line = f"使用者特別反白的文字：{selected_text}\n" if selected_text else ""
    column_rule = ("注意：選取的區塊位於並排欄位內，回傳的區塊不可以是 columns。\n"
                   if not allow_columns else "")
    prompt = f"""你在協助修改一份 paper presentation 筆記。資料夾中有 paper.pdf（需要查原文時可讀）。論文摘要：
<summary>
{summary}
</summary>
前一個區塊（僅供上下文，不要修改）：{_dump(before)}
使用者選取的區塊：{_dump(selected)}
{text_line}後一個區塊（僅供上下文，不要修改）：{_dump(after)}

使用者說：{message}

若使用者要修改內容：blocks_json 給出「取代所有選取區塊」的新區塊陣列（數量可以比原本多或少，但不可為空陣列）。
只反白部分文字時，仍回傳整個區塊，但只改動與那段文字相關的部分。
若使用者只是提問或討論、不需要修改：blocks_json 給空字串 ""。
reply 用繁體中文回覆使用者（說明你改了什麼，或回答問題）。
{column_rule}可用的圖片檔名：{', '.join(figures) or '（無）'}
{ELI5_GUIDE}
{BLOCK_FORMAT_GUIDE}
以 JSON 回傳：{{"reply": "...", "blocks_json": "..."}}"""
    reply, blocks = _call_blocks(engine, prompt, paper_dir, run, set(figures),
                                 allow_empty=True, allow_columns=allow_columns)
    return EditResult(reply, blocks)


def _strip_ids(item) -> None:
    if isinstance(item, dict):
        item.pop("id", None)
        for col in item.get("columns", []) if isinstance(item.get("columns"), list) else []:
            if isinstance(col, dict):
                for b in col.get("blocks", []) if isinstance(col.get("blocks"), list) else []:
                    _strip_ids(b)


def _parse_blocks(out: dict, figure_names: set[str], allow_empty: bool,
                  allow_columns: bool) -> tuple[str, list | None]:
    reply, raw = out.get("reply"), out.get("blocks_json")
    if not isinstance(reply, str) or not isinstance(raw, str):
        raise ValueError("缺少 reply 或 blocks_json 字串欄位")
    if raw.strip() == "":
        if allow_empty:
            return reply, None
        raise ValueError("blocks_json 不可為空字串")
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("blocks_json 必須是非空的 JSON 陣列；不修改請給空字串")
    for item in data:
        _strip_ids(item)
    blocks = BlockList.validate_python(data)
    if not allow_columns and any(b.type == "columns" for b in blocks):
        raise ValueError("選取的區塊在並排欄位內，不可回傳 columns 區塊")
    for b in flatten(blocks):
        if b.type == "chart":
            b.verified = False
        if b.type == "figure" and b.path not in figure_names:
            raise ValueError(f"figure.path「{b.path}」不在圖片清單中")
    return reply, blocks


def _call_blocks(engine, prompt: str, paper_dir: Path, run, figure_names: set[str],
                 allow_empty: bool, allow_columns: bool = True) -> tuple[str, list | None]:
    out = run(engine, prompt, BLOCKS_SCHEMA, paper_dir)
    try:
        return _parse_blocks(out, figure_names, allow_empty, allow_columns)
    except (ValueError, ValidationError) as e:
        first_error = str(e)[:1500]
    retry_prompt = (f"{prompt}\n\n你上一次的輸出格式有誤：\n{first_error}\n"
                    f"上一次的輸出：\n{json.dumps(out, ensure_ascii=False)[:4000]}\n請修正後重新輸出完整結果。")
    out2 = run(engine, retry_prompt, BLOCKS_SCHEMA, paper_dir)
    try:
        return _parse_blocks(out2, figure_names, allow_empty, allow_columns)
    except (ValueError, ValidationError) as e:
        raise AIFormatError(f"AI 回傳格式錯誤（已重試一次）：{str(e)[:500]}",
                            json.dumps(out2, ensure_ascii=False)) from e
