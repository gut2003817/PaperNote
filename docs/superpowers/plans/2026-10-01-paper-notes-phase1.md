# Paper Notes 第一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本機網頁 app：匯入論文 PDF → AI 產生報 paper 用的結構化筆記（含 ELI5 與圖表）→ 使用者選取區塊在右側聊天欄與 AI 討論，AI 直接改寫、可復原 → 圖表可拉大小／調間距／並排。

**Architecture:** 前端 React + BlockNote 區塊編輯器（自訂 chart / diagram / figure / whiteboard / eli5 區塊），經 Vite proxy 打本機 FastAPI。後端以 subprocess 呼叫本機 `claude -p` / `codex exec`，所有 AI 輸出先經 pydantic schema 驗證才進筆記。每篇論文一個資料夾（PDF、圖、note.json、快照、聊天紀錄）。

**Tech Stack:** Python 3.12、FastAPI、pydantic v2、PyMuPDF；React 19、Vite、TypeScript、BlockNote 0.55.0（含 xl-multi-column）、vega-embed、mermaid、@excalidraw/excalidraw；pytest、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-01-paper-notes-design.md`

## Global Constraints

- Python ≥ 3.12（本機為 3.12.7，用 `backend/.venv`）。
- BlockNote 相關套件全部釘死 `0.55.0`；`@blocknote/xl-multi-column` 授權為 `GPL-3.0 OR PROPRIETARY`——僅限個人使用，不得散布本 app。
- React 19；`@mantine/core` / `@mantine/hooks` 用 `^8.3.11`（BlockNote mantine 的 peer 要求）。
- AI 一律透過本機 CLI，不打 API、不需 API key。旗標固定如下（2026-10-01 實測可用），不得增減：
  - Claude：`claude -p --output-format json --strict-mcp-config --no-session-persistence --allowedTools Read Skill --disallowedTools Agent Bash Write Edit NotebookEdit WebFetch WebSearch --json-schema <schema>`，prompt 從 **stdin** 傳入，結果取 stdout JSON 的 `structured_output`。
  - Codex：`codex exec -s read-only --skip-git-repo-check --ephemeral --color never -C <論文資料夾> --output-schema <schema檔> -o <輸出檔> -`，prompt 從 stdin 傳入。
  - 禁用 `--bare`（不支援訂閱登入）與 `--dangerously-bypass-approvals-and-sandbox`。
- AI 不直接寫任何檔案；所有 AI 輸出經 `schema.py` 驗證後，才由 app 寫入或交給前端套用。
- AI 執行逾時上限 300 秒。
- AI 產生的 `chart` 一律 `verified=false`。
- 介面文字一律繁體中文。
- 資料目錄 `papers/`（可用 `PAPER_NOTES_DATA` 覆寫）不進 git。

## Review Focus

1. 使用者在編輯器插入 BlockNote 內建但筆記 schema 沒有的區塊（列表、引言），或用 Tab 做出巢狀區塊 → 自動存檔仍須成功（降級成段落、攤平），不可 422 卡死。→ Task 8 測試。
2. 選取的區塊位於並排欄位內，AI 卻回傳 `columns` → 會形成欄中欄（schema 不允許），必須視為格式錯誤並重試。→ Task 5、Task 6 測試。
3. 論文的圖是向量圖（沒有嵌入點陣圖）→ 仍要有整頁截圖可用。→ Task 3 測試。
4. 上傳的不是 PDF、PDF 損毀或有密碼 → 明確錯誤訊息，匯入工作不可卡在「執行中」。→ Task 3、Task 6 測試。
5. 同一篇筆記同時送出兩個 AI 修改（連點兩下、開兩個分頁）→ 第二個回 409，筆記不被破壞。→ Task 6 測試。

## 檔案結構

```
paper-notes/
  .gitignore
  dev.sh                          一鍵啟動前後端（Task 12）
  README.md                       （Task 12）
  backend/
    pyproject.toml
    paper_notes/
      __init__.py
      schema.py                   區塊資料模型（note.json 的唯一定義）
      storage.py                  論文資料夾讀寫、快照、聊天紀錄
      pdf_service.py              擷取 PDF 圖片
      ai_runner.py                呼叫 claude / codex CLI、登入檢查
      ai_tasks.py                 prompt、驗證、重試
      api.py                      FastAPI 路由（create_app 可注入假 AI）
      main.py                     uvicorn 進入點
    tests/
      conftest.py
      fakes.py                    FakeRun（ai_tasks / api 測試用）
      fake_cli.py                 假 claude / codex 執行檔（ai_runner 測試與 E2E 用）
      make_sample_pdf.py          產生測試 PDF
      test_schema.py  test_storage.py  test_pdf_service.py
      test_ai_runner.py  test_ai_tasks.py  test_api.py
  frontend/
    package.json  tsconfig.json  vite.config.ts  index.html  playwright.config.ts
    src/
      main.tsx  App.tsx  styles.css  types.ts  api.ts  api.test.ts
      pages/PaperList.tsx  pages/PaperView.tsx  HealthLight.tsx
      convert/inline.ts  convert/note.ts  convert/fixtures.ts  convert/note.test.ts
      editor/layout.ts  editor/layout.test.ts  editor/ResizableFrame.tsx
      editor/blocks.tsx  editor/schema.ts  editor/schema.test.ts
      editor/slugStore.ts  editor/NoteEditor.tsx
      chat/ChatPanel.tsx  chat/ChatPanel.test.tsx
    e2e/fixtures/ai-responses.json  e2e/app.spec.ts
```

## 外包給 Codex（使用者規則 `~/.claude/rules/dispatch.md` §7）

本計畫每個 Task 都附完整程式碼與可執行的驗收命令，符合「大、規格明確、可驗收」。建議：

- **Task 1–6、8**（後端與純邏輯轉換）：派 Codex 實作，命令：
  ```bash
  codex exec -s workspace-write -C ~/projects/paper-notes --skip-git-repo-check --color never \
    -o <SP>/codex_task<N>.md \
    "依照 docs/superpowers/plans/2026-10-01-paper-notes-phase1.md 的 Task <N> 逐步實作（含寫測試、跑測試、commit）。只做 Task <N>。完成後只回：改了哪些檔、測試命令與 pass/fail 數字，≤30 行。" \
    > <SP>/codex_task<N>.log 2>&1
  ```
  Claude 端驗收：自己重跑該 Task 的測試命令並抽查一個檔案。
- **Task 7、9–11**（前端 UI）：同上派 Codex；UI 若與 BlockNote 實際 API 不合，以 `node_modules/@blocknote/*/types` 為準修正。
- **Task 12**（E2E 與真實論文驗收）：Claude 主對話執行，最後真實論文那步需要使用者一起看。

---

### Task 1: 後端骨架與區塊 schema

**Files:**
- Create: `.gitignore`
- Create: `backend/pyproject.toml`
- Create: `backend/paper_notes/__init__.py`（空檔）
- Create: `backend/paper_notes/schema.py`
- Test: `backend/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `Layout`、`Heading`、`Paragraph`、`Eli5`、`Chart`、`Diagram`、`Figure`、`Whiteboard`、`Column`、`Columns`（pydantic models，`type` 欄位為鑑別子）
  - `Note(blocks: list[Block])`
  - `BlockList: TypeAdapter[list[Block]]`（`BlockList.validate_python(data)`）
  - `flatten(blocks) -> list`：依文件順序攤平，columns 本身與其內部區塊都列入
  - `new_id() -> str`：10 字元 hex

- [ ] **Step 1: 建立專案設定與虛擬環境**

`.gitignore`：
```gitignore
papers/
.e2e/
backend/.venv/
__pycache__/
*.egg-info/
.pytest_cache/
frontend/node_modules/
frontend/dist/
frontend/test-results/
frontend/playwright-report/
```

`backend/pyproject.toml`：
```toml
[project]
name = "paper-notes"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "pydantic>=2.8",
  "pymupdf>=1.24",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["paper_notes"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Run:
```bash
cd ~/projects/paper-notes/backend && touch paper_notes/__init__.py 2>/dev/null || (mkdir -p paper_notes tests && touch paper_notes/__init__.py)
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
.venv/bin/python -c "import fitz, fastapi, pydantic; print('ok')"
```
Expected: `ok`

- [ ] **Step 2: 寫失敗的測試**

`backend/tests/test_schema.py`：
```python
import pytest
from pydantic import ValidationError

from paper_notes.schema import BlockList, Note, flatten

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]},
       "encoding": {"x": {"field": "x"}, "y": {"field": "y", "type": "quantitative"}}}


def test_valid_note_with_all_block_types_and_auto_ids():
    note = Note.model_validate({"blocks": [
        {"type": "heading", "level": 1, "text": "標題"},
        {"type": "paragraph", "text": "**粗體**"},
        {"type": "eli5", "text": "像是..."},
        {"type": "chart", "spec": BAR, "source": "Table 2, p.7"},
        {"type": "diagram", "mermaid": "flowchart LR\n A-->B"},
        {"type": "figure", "path": "p3-1.png", "caption": "架構", "page": 3,
         "layout": {"widthPct": 50, "align": "left"}},
        {"type": "whiteboard"},
        {"type": "columns", "columns": [
            {"widthPct": 40, "blocks": [{"type": "paragraph", "text": "左"}]},
            {"widthPct": 60, "blocks": [{"type": "eli5", "text": "右"}]},
        ]},
    ]})
    assert len(note.blocks) == 8
    assert all(len(b.id) == 10 for b in note.blocks)
    assert note.blocks[3].verified is False
    assert note.blocks[5].layout.widthPct == 50
    assert note.blocks[6].scene == {"elements": []}


def test_chart_spec_without_view_key_rejected():
    with pytest.raises(ValidationError, match="mark"):
        BlockList.validate_python([{"type": "chart", "spec": {"data": {}}, "source": ""}])


def test_columns_widths_must_sum_to_100():
    with pytest.raises(ValidationError, match="100"):
        BlockList.validate_python([{"type": "columns", "columns": [
            {"widthPct": 30, "blocks": [{"type": "paragraph", "text": "a"}]},
            {"widthPct": 30, "blocks": [{"type": "paragraph", "text": "b"}]},
        ]}])


def test_columns_cannot_nest():
    inner = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]},
    ]}
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "columns", "columns": [
            {"widthPct": 50, "blocks": [inner]},
            {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "c"}]},
        ]}])


@pytest.mark.parametrize("path", ["../secret.png", "a/b.png", "x.jpg", ""])
def test_figure_path_rejects_traversal_and_non_png(path):
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "figure", "path": path, "page": 1}])


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "paragraph", "text": "a", "color": "red"}])


def test_heading_level_limited_to_3():
    with pytest.raises(ValidationError):
        BlockList.validate_python([{"type": "heading", "level": 4, "text": "a"}])


def test_flatten_document_order():
    blocks = BlockList.validate_python([
        {"id": "a", "type": "paragraph", "text": "a"},
        {"id": "c", "type": "columns", "columns": [
            {"widthPct": 50, "blocks": [{"id": "c1", "type": "paragraph", "text": "1"}]},
            {"widthPct": 50, "blocks": [{"id": "c2", "type": "paragraph", "text": "2"}]},
        ]},
        {"id": "z", "type": "paragraph", "text": "z"},
    ])
    assert [b.id for b in flatten(blocks)] == ["a", "c", "c1", "c2", "z"]
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd ~/projects/paper-notes/backend && .venv/bin/pytest tests/test_schema.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'paper_notes.schema'`）

- [ ] **Step 4: 實作**

`backend/paper_notes/schema.py`：
```python
"""筆記區塊的資料模型（note.json 的唯一定義）。"""
from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


def new_id() -> str:
    return uuid4().hex[:10]


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widthPct: float = Field(100, ge=10, le=100)
    heightPx: int | None = Field(None, ge=50, le=2000)
    marginTopPx: int = Field(8, ge=0, le=200)
    marginBottomPx: int = Field(8, ge=0, le=200)
    align: Literal["left", "center", "right"] = "center"


class _Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=new_id, min_length=1)
    layout: Layout | None = None


class Heading(_Block):
    type: Literal["heading"]
    level: int = Field(ge=1, le=3)
    text: str


class Paragraph(_Block):
    type: Literal["paragraph"]
    text: str


class Eli5(_Block):
    type: Literal["eli5"]
    text: str


_VEGA_VIEW_KEYS = {"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"}


class Chart(_Block):
    type: Literal["chart"]
    spec: dict
    source: str = ""
    verified: bool = False

    @field_validator("spec")
    @classmethod
    def _spec_has_view(cls, v: dict) -> dict:
        if not _VEGA_VIEW_KEYS & v.keys():
            raise ValueError("Vega-Lite spec 需要 mark/layer/concat 等其中一個欄位")
        return v


class Diagram(_Block):
    type: Literal["diagram"]
    mermaid: str = Field(min_length=1)


class Figure(_Block):
    type: Literal["figure"]
    path: str = Field(pattern=r"^[\w.-]+\.png$")
    caption: str = ""
    page: int = Field(ge=1)


class Whiteboard(_Block):
    type: Literal["whiteboard"]
    scene: dict = Field(default_factory=lambda: {"elements": []})


LeafBlock = Annotated[
    Union[Heading, Paragraph, Eli5, Chart, Diagram, Figure, Whiteboard],
    Field(discriminator="type"),
]


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widthPct: float = Field(ge=10, le=90)
    blocks: list[LeafBlock] = Field(min_length=1)


class Columns(_Block):
    type: Literal["columns"]
    columns: list[Column] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _widths_sum_to_100(self):
        total = sum(c.widthPct for c in self.columns)
        if abs(total - 100) > 1:
            raise ValueError(f"欄寬總和必須是 100，目前是 {total}")
        return self


Block = Annotated[
    Union[Heading, Paragraph, Eli5, Chart, Diagram, Figure, Whiteboard, Columns],
    Field(discriminator="type"),
]


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[Block]


BlockList = TypeAdapter(list[Block])


def flatten(blocks: list) -> list:
    """依文件順序攤平；columns 本身與其內部區塊都列入。"""
    out = []
    for b in blocks:
        out.append(b)
        if b.type == "columns":
            for col in b.columns:
                out.extend(col.blocks)
    return out
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_schema.py -q`
Expected: `11 passed`

- [ ] **Step 6: Commit**

```bash
cd ~/projects/paper-notes && git add .gitignore backend && git commit -m "feat(backend): project scaffold and note block schema"
```

---

### Task 2: storage（論文資料夾、快照、聊天紀錄）

**Files:**
- Create: `backend/paper_notes/storage.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `Note`（Task 1）
- Produces:
  - `class NotFound(Exception)`
  - `@dataclass PaperInfo(slug: str, title: str, created: float, has_note: bool)`
  - `class Storage(root: Path)`，方法：
    `create_paper(title: str, pdf_bytes: bytes) -> str`、`list_papers() -> list[PaperInfo]`、`paper_dir(slug) -> Path`、
    `figures_dir(slug) -> Path`、`figure_path(slug, name) -> Path`、
    `read_note(slug) -> Note`、`write_note(slug, note: Note) -> None`、
    `read_summary(slug) -> str`（無檔回 `""`）、`write_summary(slug, text: str) -> None`、
    `snapshot(slug) -> str`（回快照檔名）、`restore(slug, name) -> Note`、
    `append_chat(slug, entry: dict) -> None`、`read_chat(slug) -> list[dict]`
  - 所有方法遇到不存在或不合法的 slug／檔名一律丟 `NotFound`

- [ ] **Step 1: 寫失敗的測試**

`backend/tests/test_storage.py`：
```python
import time

import pytest

from paper_notes.schema import Note
from paper_notes.storage import NotFound, Storage


@pytest.fixture
def st(tmp_path):
    return Storage(tmp_path / "papers")


def _note(text):
    return Note.model_validate({"blocks": [{"id": "p1", "type": "paragraph", "text": text}]})


def test_create_and_list(st):
    slug = st.create_paper("Attention Is All You Need", b"%PDF-1.4 fake")
    assert slug.startswith("attention-is-all-you-need-")
    assert (st.paper_dir(slug) / "paper.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert st.figures_dir(slug).is_dir()
    [info] = st.list_papers()
    assert info.slug == slug and info.title == "Attention Is All You Need" and info.has_note is False


def test_chinese_title_gets_generic_slug(st):
    slug = st.create_paper("注意力機制", b"%PDF")
    assert slug.startswith("paper-")
    assert st.list_papers()[0].title == "注意力機制"


def test_list_sorted_newest_first(st):
    a = st.create_paper("a", b"%PDF")
    time.sleep(0.01)
    b = st.create_paper("b", b"%PDF")
    assert [p.slug for p in st.list_papers()] == [b, a]


@pytest.mark.parametrize("slug", ["../etc", "nope", "A-B", ""])
def test_bad_or_missing_slug(st, slug):
    with pytest.raises(NotFound):
        st.paper_dir(slug)


def test_note_round_trip_and_has_note(st):
    slug = st.create_paper("x", b"%PDF")
    with pytest.raises(NotFound):
        st.read_note(slug)
    st.write_note(slug, _note("hello"))
    assert st.read_note(slug).blocks[0].text == "hello"
    assert st.list_papers()[0].has_note is True
    assert "heightPx" not in (st.paper_dir(slug) / "note.json").read_text()


def test_summary_default_empty(st):
    slug = st.create_paper("x", b"%PDF")
    assert st.read_summary(slug) == ""
    st.write_summary(slug, "# 摘要")
    assert st.read_summary(slug) == "# 摘要"


def test_snapshot_and_restore(st):
    slug = st.create_paper("x", b"%PDF")
    st.write_note(slug, _note("v1"))
    name = st.snapshot(slug)
    st.write_note(slug, _note("v2"))
    restored = st.restore(slug, name)
    assert restored.blocks[0].text == "v1"
    assert st.read_note(slug).blocks[0].text == "v1"


@pytest.mark.parametrize("name", ["../note.json", "20260101-000000-zzzz.json", "x.json"])
def test_restore_rejects_bad_names(st, name):
    slug = st.create_paper("x", b"%PDF")
    st.write_note(slug, _note("v1"))
    with pytest.raises(NotFound):
        st.restore(slug, name)


def test_chat_append_and_read(st):
    slug = st.create_paper("x", b"%PDF")
    assert st.read_chat(slug) == []
    st.append_chat(slug, {"role": "user", "text": "你好"})
    st.append_chat(slug, {"role": "assistant", "text": "嗨"})
    chat = st.read_chat(slug)
    assert [c["text"] for c in chat] == ["你好", "嗨"]
    assert all("ts" in c for c in chat)


def test_figure_path_validation(st):
    slug = st.create_paper("x", b"%PDF")
    (st.figures_dir(slug) / "p1-1.png").write_bytes(b"png")
    assert st.figure_path(slug, "p1-1.png").exists()
    for bad in ["../paper.pdf", "missing.png", "p1-1.jpg"]:
        with pytest.raises(NotFound):
            st.figure_path(slug, bad)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_storage.py -q`
Expected: FAIL（`No module named 'paper_notes.storage'`）

- [ ] **Step 3: 實作**

`backend/paper_notes/storage.py`：
```python
"""論文資料夾的讀寫。所有路徑都經過這裡，防止 slug／檔名穿越目錄。"""
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .schema import Note

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,80}$")
_SNAPSHOT_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}\.json$")
_FIGURE_RE = re.compile(r"^[\w.-]+\.png$")


class NotFound(Exception):
    pass


@dataclass
class PaperInfo:
    slug: str
    title: str
    created: float
    has_note: bool


def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "paper"
    return f"{base}-{uuid4().hex[:6]}"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def paper_dir(self, slug: str) -> Path:
        if not _SLUG_RE.match(slug):
            raise NotFound(slug)
        d = self.root / slug
        if not d.is_dir():
            raise NotFound(slug)
        return d

    def create_paper(self, title: str, pdf_bytes: bytes) -> str:
        slug = _slugify(title)
        d = self.root / slug
        (d / "figures").mkdir(parents=True)
        (d / "history").mkdir()
        (d / "paper.pdf").write_bytes(pdf_bytes)
        _atomic_write(d / "meta.json",
                      json.dumps({"title": title, "created": time.time()}, ensure_ascii=False))
        return slug

    def list_papers(self) -> list[PaperInfo]:
        out = []
        for d in self.root.iterdir():
            meta = d / "meta.json"
            if d.is_dir() and meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                out.append(PaperInfo(d.name, m["title"], m["created"], (d / "note.json").exists()))
        return sorted(out, key=lambda p: p.created, reverse=True)

    def figures_dir(self, slug: str) -> Path:
        return self.paper_dir(slug) / "figures"

    def figure_path(self, slug: str, name: str) -> Path:
        if not _FIGURE_RE.match(name):
            raise NotFound(name)
        p = self.figures_dir(slug) / name
        if not p.is_file():
            raise NotFound(name)
        return p

    def read_note(self, slug: str) -> Note:
        p = self.paper_dir(slug) / "note.json"
        if not p.exists():
            raise NotFound(f"{slug}/note.json")
        return Note.model_validate_json(p.read_text(encoding="utf-8"))

    def write_note(self, slug: str, note: Note) -> None:
        _atomic_write(self.paper_dir(slug) / "note.json",
                      note.model_dump_json(indent=2, exclude_none=True))

    def read_summary(self, slug: str) -> str:
        p = self.paper_dir(slug) / "summary.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_summary(self, slug: str, text: str) -> None:
        _atomic_write(self.paper_dir(slug) / "summary.md", text)

    def snapshot(self, slug: str) -> str:
        d = self.paper_dir(slug)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:4]}.json"
        _atomic_write(d / "history" / name, (d / "note.json").read_text(encoding="utf-8"))
        return name

    def restore(self, slug: str, name: str) -> Note:
        if not _SNAPSHOT_RE.match(name):
            raise NotFound(name)
        p = self.paper_dir(slug) / "history" / name
        if not p.is_file():
            raise NotFound(name)
        note = Note.model_validate_json(p.read_text(encoding="utf-8"))
        self.write_note(slug, note)
        return note

    def append_chat(self, slug: str, entry: dict) -> None:
        line = json.dumps({**entry, "ts": time.time()}, ensure_ascii=False)
        with open(self.paper_dir(slug) / "chat.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_chat(self, slug: str) -> list[dict]:
        p = self.paper_dir(slug) / "chat.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_storage.py -q`
Expected: 全數 passed（15 passed）

- [ ] **Step 5: Commit**

```bash
git add backend && git commit -m "feat(backend): paper folder storage with snapshots and chat log"
```

---

### Task 3: pdf_service（擷取圖片）

**Files:**
- Create: `backend/tests/make_sample_pdf.py`
- Create: `backend/paper_notes/pdf_service.py`
- Test: `backend/tests/test_pdf_service.py`

**Interfaces:**
- Produces:
  - `@dataclass FigureInfo(file: str, page: int, kind: str, width: int, height: int)`，`kind` 為 `"embedded"` 或 `"page"`
  - `class PdfError(Exception)`
  - `extract_figures(pdf_path: Path, out_dir: Path, min_side: int = 120, page_zoom: float = 1.5) -> list[FigureInfo]`：嵌入點陣圖存成 `p{頁}-{序}.png`（跳過任一邊 < min_side 的小圖），另外每頁存整頁截圖 `page-{頁}.png`（向量圖的退路）
  - `tests/make_sample_pdf.py`：`make_sample_pdf(path: Path) -> Path`，也可 `python tests/make_sample_pdf.py <out.pdf>`（E2E 用）

- [ ] **Step 1: 建立測試 PDF 產生器**

`backend/tests/make_sample_pdf.py`：
```python
"""產生測試用 PDF：第 1 頁有文字與一張 200x150 圖；第 2 頁有文字與一張 20x20 小圖。"""
import sys
from pathlib import Path

import fitz


def _png(w: int, h: int, gray: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.clear_with(gray)
    return pix.tobytes("png")


def make_sample_pdf(path: Path) -> Path:
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Sample Paper Title", fontsize=20)
    p1.insert_image(fitz.Rect(72, 100, 272, 250), stream=_png(200, 150, 180))
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Results", fontsize=14)
    p2.insert_image(fitz.Rect(72, 100, 92, 120), stream=_png(20, 20, 90))
    doc.save(path)
    doc.close()
    return Path(path)


if __name__ == "__main__":
    make_sample_pdf(Path(sys.argv[1]))
```

- [ ] **Step 2: 寫失敗的測試**

`backend/tests/test_pdf_service.py`：
```python
import fitz
import pytest

from make_sample_pdf import make_sample_pdf
from paper_notes.pdf_service import PdfError, extract_figures


def test_extracts_embedded_images_and_page_renders(tmp_path):
    pdf = make_sample_pdf(tmp_path / "s.pdf")
    figs = extract_figures(pdf, tmp_path / "figures")
    names = [f.file for f in figs]
    assert "p1-1.png" in names
    assert not any(n.startswith("p2-") for n in names), "20x20 小圖應被略過"
    assert "page-1.png" in names and "page-2.png" in names
    emb = next(f for f in figs if f.file == "p1-1.png")
    assert (emb.page, emb.kind, emb.width, emb.height) == (1, "embedded", 200, 150)
    for f in figs:
        assert (tmp_path / "figures" / f.file).stat().st_size > 0


def test_vector_only_pdf_still_has_page_renders(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 300, 200), color=(0, 0, 1))
    page.insert_text((60, 80), "Figure 1: vector diagram")
    doc.save(tmp_path / "v.pdf")
    figs = extract_figures(tmp_path / "v.pdf", tmp_path / "figures")
    assert [(f.file, f.kind) for f in figs] == [("page-1.png", "page")]


def test_corrupt_pdf_raises_pdf_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(PdfError):
        extract_figures(bad, tmp_path / "figures")


def test_encrypted_pdf_raises_pdf_error(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(tmp_path / "enc.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(PdfError, match="密碼"):
        extract_figures(tmp_path / "enc.pdf", tmp_path / "figures")
```

在 `backend/tests/conftest.py` 加入（讓測試能 import `make_sample_pdf`；後續 Task 會再往此檔追加 fixture）：
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_pdf_service.py -q`
Expected: FAIL（`No module named 'paper_notes.pdf_service'`）

- [ ] **Step 4: 實作**

`backend/paper_notes/pdf_service.py`：
```python
"""從 PDF 擷取圖片：嵌入的點陣圖，加上每頁整頁截圖（論文常見的向量圖靠這個）。"""
from dataclasses import dataclass
from pathlib import Path

import fitz


class PdfError(Exception):
    pass


@dataclass
class FigureInfo:
    file: str
    page: int
    kind: str  # "embedded" | "page"
    width: int
    height: int


def extract_figures(pdf_path: Path, out_dir: Path, min_side: int = 120,
                    page_zoom: float = 1.5) -> list[FigureInfo]:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise PdfError(f"無法開啟 PDF：{e}") from e
    with doc:
        if doc.needs_pass:
            raise PdfError("PDF 有密碼保護，請先移除密碼再上傳")
        if doc.page_count == 0:
            raise PdfError("PDF 沒有任何頁面")
        out_dir.mkdir(parents=True, exist_ok=True)
        figures: list[FigureInfo] = []
        seen: set[int] = set()
        for pno, page in enumerate(doc, start=1):
            for i, img in enumerate(page.get_images(full=True), start=1):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                pix = fitz.Pixmap(doc, xref)
                if pix.width < min_side or pix.height < min_side:
                    continue
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                name = f"p{pno}-{i}.png"
                pix.save(out_dir / name)
                figures.append(FigureInfo(name, pno, "embedded", pix.width, pix.height))
            render = page.get_pixmap(matrix=fitz.Matrix(page_zoom, page_zoom))
            name = f"page-{pno}.png"
            render.save(out_dir / name)
            figures.append(FigureInfo(name, pno, "page", render.width, render.height))
    return figures
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_pdf_service.py -q`
Expected: `4 passed`。若 `test_corrupt_pdf_raises_pdf_error` 失敗是因為 PyMuPDF 對該內容沒有在 `open` 時報錯，而是 `page_count == 0`——那已被 `PdfError("PDF 沒有任何頁面")` 涵蓋；若兩者都沒觸發，把損毀內容改成 `b"not a pdf at all"` 並在測試中說明原因。

- [ ] **Step 6: Commit**

```bash
git add backend && git commit -m "feat(backend): extract embedded figures and page renders from PDF"
```

---

### Task 4: ai_runner（呼叫 CLI）與假 CLI

**Files:**
- Create: `backend/tests/fake_cli.py`
- Modify: `backend/tests/conftest.py`（追加 `fake_ai` fixture）
- Create: `backend/paper_notes/ai_runner.py`
- Test: `backend/tests/test_ai_runner.py`

**Interfaces:**
- Produces:
  - `Engine = Literal["claude", "codex"]`
  - `class AIError(Exception)`：訊息是給使用者看的繁中說明
  - `run(engine: Engine, prompt: str, schema: dict, workdir: Path, timeout: int = 300) -> dict`
  - `check_engine(engine: Engine) -> dict`：`{"ok": bool, "detail": str, "fix"?: str}`
  - `claude_command(schema: dict) -> list[str]`、`codex_command(workdir, schema_file, out_file) -> list[str]`
  - 環境變數 `PAPER_NOTES_CLAUDE_BIN` / `PAPER_NOTES_CODEX_BIN` 可覆寫執行檔路徑（測試與 E2E 用）
  - `tests/fake_cli.py`：同時扮演 claude 與 codex；環境變數 `FAKE_AI_RESPONSES`（JSON 陣列檔，依序回應）、`FAKE_AI_STATE`（計數檔）、`FAKE_AI_LOG`（記錄 prompt）、`FAKE_AI_SLEEP`、`FAKE_AI_FAIL=1`

- [ ] **Step 1: 建立假 CLI 與 fixture**

`backend/tests/fake_cli.py`：
```python
#!/usr/bin/env python3
"""測試用假 CLI，同時扮演 claude 與 codex。

環境變數：
  FAKE_AI_RESPONSES  JSON 檔路徑，內容是回應陣列；每次呼叫依序取一個（取完重複最後一個）
  FAKE_AI_STATE      呼叫計數檔路徑
  FAKE_AI_LOG        把收到的 prompt（stdin）附加寫入此檔
  FAKE_AI_SLEEP      秒數，模擬很慢的 AI
  FAKE_AI_FAIL       設為 1 時模擬 CLI 失敗
"""
import json
import os
import sys
import time
from pathlib import Path


def next_response():
    responses = json.loads(Path(os.environ["FAKE_AI_RESPONSES"]).read_text(encoding="utf-8"))
    state = Path(os.environ["FAKE_AI_STATE"])
    i = int(state.read_text()) if state.exists() else 0
    state.write_text(str(i + 1))
    return responses[min(i, len(responses) - 1)]


def main():
    args = sys.argv[1:]
    fail = os.environ.get("FAKE_AI_FAIL") == "1"
    if args[:2] in (["auth", "status"], ["login", "status"]):
        print('{"loggedIn": false}' if fail else '{"loggedIn": true}')
        sys.exit(1 if fail else 0)

    prompt = sys.stdin.read()
    if log := os.environ.get("FAKE_AI_LOG"):
        with open(log, "a", encoding="utf-8") as f:
            f.write(prompt + "\n=====\n")
    time.sleep(float(os.environ.get("FAKE_AI_SLEEP", "0")))

    if args and args[0] == "exec":
        if fail:
            print("codex boom", file=sys.stderr)
            sys.exit(1)
        out = args[args.index("-o") + 1]
        Path(out).write_text(json.dumps(next_response(), ensure_ascii=False), encoding="utf-8")
        return
    if fail:
        print(json.dumps({"is_error": True, "subtype": "error_during_execution", "result": "claude boom"}))
        return
    print(json.dumps({"is_error": False, "subtype": "success",
                      "structured_output": next_response()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

在 `backend/tests/conftest.py` 末尾追加：
```python
import json

import pytest

FAKE_CLI = Path(__file__).parent / "fake_cli.py"


class FakeAI:
    def __init__(self, tmp: Path):
        self.responses = tmp / "fake_responses.json"
        self.state = tmp / "fake_state"
        self.log = tmp / "fake_prompts.log"

    def set(self, responses: list) -> None:
        self.responses.write_text(json.dumps(responses, ensure_ascii=False), encoding="utf-8")
        self.state.unlink(missing_ok=True)

    def prompts(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").split("\n=====\n")[:-1]


@pytest.fixture
def fake_ai(tmp_path, monkeypatch):
    FAKE_CLI.chmod(0o755)
    fake = FakeAI(tmp_path)
    for key, value in {
        "PAPER_NOTES_CLAUDE_BIN": str(FAKE_CLI),
        "PAPER_NOTES_CODEX_BIN": str(FAKE_CLI),
        "FAKE_AI_RESPONSES": str(fake.responses),
        "FAKE_AI_STATE": str(fake.state),
        "FAKE_AI_LOG": str(fake.log),
    }.items():
        monkeypatch.setenv(key, value)
    fake.set([{}])
    return fake
```

- [ ] **Step 2: 寫失敗的測試**

`backend/tests/test_ai_runner.py`：
```python
from pathlib import Path

import pytest

from paper_notes import ai_runner
from paper_notes.ai_runner import AIError, check_engine, claude_command, run

SCHEMA = {"type": "object", "properties": {"content": {"type": "string"}},
          "required": ["content"], "additionalProperties": False}


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_run_returns_structured_output_and_sends_prompt_via_stdin(fake_ai, tmp_path, engine):
    fake_ai.set([{"content": "你好"}])
    assert run(engine, "讀 paper.pdf", SCHEMA, tmp_path) == {"content": "你好"}
    assert fake_ai.prompts() == ["讀 paper.pdf"]


def test_claude_command_flags_and_no_prompt_in_argv():
    cmd = claude_command(SCHEMA)
    for flag in ["-p", "--output-format", "--strict-mcp-config", "--no-session-persistence",
                 "--allowedTools", "--disallowedTools", "--json-schema"]:
        assert flag in cmd
    assert "Bash" in cmd[cmd.index("--disallowedTools"):]
    assert "--bare" not in cmd


@pytest.mark.parametrize("engine,msg", [("claude", "claude 回報錯誤"), ("codex", "codex 失敗")])
def test_cli_failure_raises(fake_ai, tmp_path, monkeypatch, engine, msg):
    monkeypatch.setenv("FAKE_AI_FAIL", "1")
    with pytest.raises(AIError, match=msg):
        run(engine, "x", SCHEMA, tmp_path)


def test_timeout_raises(fake_ai, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AI_SLEEP", "3")
    with pytest.raises(AIError, match="超過 1 秒"):
        run("claude", "x", SCHEMA, tmp_path, timeout=1)


def test_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_NOTES_CLAUDE_BIN", str(tmp_path / "nope"))
    with pytest.raises(AIError, match="找不到 claude"):
        run("claude", "x", SCHEMA, tmp_path)


def test_unknown_engine(tmp_path):
    with pytest.raises(AIError, match="未知的引擎"):
        run("gemini", "x", SCHEMA, tmp_path)  # type: ignore[arg-type]


def test_check_engine_ok_and_not_logged_in(fake_ai, monkeypatch):
    assert check_engine("claude") == {"ok": True, "detail": "已登入"}
    monkeypatch.setenv("FAKE_AI_FAIL", "1")
    res = check_engine("codex")
    assert res["ok"] is False and "未登入" in res["detail"] and res["fix"]


def test_check_engine_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_NOTES_CODEX_BIN", str(tmp_path / "nope"))
    res = check_engine("codex")
    assert res["ok"] is False and "找不到" in res["detail"]
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_ai_runner.py -q`
Expected: FAIL（`cannot import name ... from paper_notes`）

- [ ] **Step 4: 實作**

`backend/paper_notes/ai_runner.py`：
```python
"""呼叫本機 claude / codex CLI，取回符合 JSON schema 的結果。旗標已於 2026-10-01 實測。"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

Engine = Literal["claude", "codex"]
DEFAULT_TIMEOUT = 300
_CLAUDE_DENY = ["Agent", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]


class AIError(Exception):
    """CLI 找不到、逾時或回報錯誤。訊息直接給使用者看。"""


def _bin(engine: str) -> str:
    return os.environ.get(f"PAPER_NOTES_{engine.upper()}_BIN", engine)


def claude_command(schema: dict) -> list[str]:
    return [_bin("claude"), "-p", "--output-format", "json", "--strict-mcp-config",
            "--no-session-persistence", "--allowedTools", "Read", "Skill",
            "--disallowedTools", *_CLAUDE_DENY, "--json-schema", json.dumps(schema)]


def codex_command(workdir: Path, schema_file: Path, out_file: Path) -> list[str]:
    return [_bin("codex"), "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
            "--color", "never", "-C", str(workdir), "--output-schema", str(schema_file),
            "-o", str(out_file), "-"]


def _tail(text: str, n: int = 800) -> str:
    return text[-n:]


def run(engine: Engine, prompt: str, schema: dict, workdir: Path,
        timeout: int = DEFAULT_TIMEOUT) -> dict:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        out_file = tmp / "out.json"
        if engine == "claude":
            cmd = claude_command(schema)
        elif engine == "codex":
            schema_file = tmp / "schema.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            cmd = codex_command(workdir, schema_file, out_file)
        else:
            raise AIError(f"未知的引擎：{engine}")
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  cwd=workdir, timeout=timeout)
        except FileNotFoundError:
            raise AIError(f"找不到 {engine} CLI，請確認已安裝並在 PATH 上") from None
        except subprocess.TimeoutExpired:
            raise AIError(f"{engine} 超過 {timeout} 秒未完成，已中止") from None
        if engine == "claude":
            return _parse_claude(proc)
        return _parse_codex(proc, out_file)


def _parse_claude(proc: subprocess.CompletedProcess) -> dict:
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AIError(f"claude 輸出不是 JSON（exit {proc.returncode}）："
                      f"{_tail(proc.stdout + proc.stderr)}") from None
    if data.get("is_error") or data.get("subtype") != "success":
        raise AIError(f"claude 回報錯誤：{_tail(str(data.get('result', '')))}")
    out = data.get("structured_output")
    if not isinstance(out, dict):
        raise AIError("claude 沒有回傳 structured_output")
    return out


def _parse_codex(proc: subprocess.CompletedProcess, out_file: Path) -> dict:
    if proc.returncode != 0 or not out_file.exists():
        raise AIError(f"codex 失敗（exit {proc.returncode}）：{_tail(proc.stderr or proc.stdout)}")
    try:
        out = json.loads(out_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise AIError(f"codex 輸出不是 JSON：{_tail(out_file.read_text(encoding='utf-8'))}") from None
    if not isinstance(out, dict):
        raise AIError("codex 輸出不是 JSON 物件")
    return out


def check_engine(engine: Engine) -> dict:
    if engine == "claude":
        cmd, fix = [_bin("claude"), "auth", "status"], "在終端機執行 claude，依提示登入"
    else:
        cmd, fix = [_bin("codex"), "login", "status"], "在終端機執行 codex login"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return {"ok": False, "detail": f"找不到 {engine} CLI", "fix": f"安裝 {engine} 並確認在 PATH 上"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{engine} 狀態檢查逾時", "fix": fix}
    logged_in = proc.returncode == 0
    if engine == "claude" and logged_in:
        try:
            logged_in = json.loads(proc.stdout).get("loggedIn") is True
        except json.JSONDecodeError:
            pass
    if logged_in:
        return {"ok": True, "detail": "已登入"}
    return {"ok": False, "detail": f"{engine} 未登入", "fix": fix}
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_ai_runner.py -q`
Expected: 全數 passed（10 passed）

- [ ] **Step 6: Commit**

```bash
git add backend && git commit -m "feat(backend): CLI runner for claude/codex with fake CLI for tests"
```

---

### Task 5: ai_tasks（prompt、驗證、重試）

**Files:**
- Create: `backend/tests/fakes.py`
- Create: `backend/paper_notes/ai_tasks.py`
- Test: `backend/tests/test_ai_tasks.py`

**Interfaces:**
- Consumes: `ai_runner.run`、`AIError`、`Engine`（Task 4）；`BlockList`、`flatten`（Task 1）；`FigureInfo`（Task 3）
- Produces:
  - `SUMMARY_SCHEMA`、`BLOCKS_SCHEMA`（dict）
  - `class AIFormatError(AIError)`，屬性 `raw: str`
  - `generate_summary(engine, paper_dir: Path, run=ai_runner.run) -> str`
  - `generate_note(engine, paper_dir: Path, summary: str, figures: list[FigureInfo], run=ai_runner.run) -> list[Block]`
  - `@dataclass EditResult(reply: str, replace: list[Block] | None)`
  - `edit_selection(engine, paper_dir, summary: str, selected: list[dict], selected_text: str, before: dict | None, after: dict | None, message: str, figures: list[str], allow_columns: bool = True, run=ai_runner.run) -> EditResult`
  - `tests/fakes.py`：`FakeRun(outputs: list[dict])`，可呼叫，記錄 `.prompts`；輸出為 `Exception` 實例時直接丟出

**設計說明（給實作者）：** AI 回傳的區塊用「JSON 字串欄位 `blocks_json`」而不是巢狀物件，因為 Codex 的 `--output-schema` 是嚴格模式（每層都要 `additionalProperties: false`、不支援 discriminated union），兩個引擎共用最簡單的 schema `{reply: string, blocks_json: string}`，真正的區塊驗證在 Python 端用 pydantic 做。

- [ ] **Step 1: 建立 FakeRun**

`backend/tests/fakes.py`：
```python
class FakeRun:
    """取代 ai_runner.run：依序回傳 outputs，記錄每次的 prompt。"""

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.prompts: list[str] = []
        self.engines: list[str] = []

    def __call__(self, engine, prompt, schema, workdir, timeout=300):
        self.prompts.append(prompt)
        self.engines.append(engine)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
```

- [ ] **Step 2: 寫失敗的測試**

`backend/tests/test_ai_tasks.py`：
```python
import json

import pytest

from fakes import FakeRun
from paper_notes.ai_runner import AIError
from paper_notes.ai_tasks import AIFormatError, edit_selection, generate_note, generate_summary
from paper_notes.pdf_service import FigureInfo

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]}}
FIGS = [FigureInfo("p3-1.png", 3, "embedded", 400, 300), FigureInfo("page-3.png", 3, "page", 900, 1200)]


def blocks_out(blocks, reply="ok"):
    return {"reply": reply, "blocks_json": json.dumps(blocks, ensure_ascii=False)}


def test_generate_summary(tmp_path):
    run = FakeRun([{"summary_md": "# 摘要\n" + "重點內容。" * 20}])
    assert generate_summary("claude", tmp_path, run=run).startswith("# 摘要")
    assert "paper.pdf" in run.prompts[0]


def test_generate_summary_too_short(tmp_path):
    with pytest.raises(AIFormatError):
        generate_summary("claude", tmp_path, run=FakeRun([{"summary_md": "短"}]))


def test_generate_note_assigns_ids_and_forces_unverified(tmp_path):
    run = FakeRun([blocks_out([
        {"id": "dup", "type": "heading", "level": 1, "text": "標題"},
        {"type": "chart", "spec": BAR, "source": "Table 1, p.5", "verified": True},
        {"type": "figure", "path": "p3-1.png", "caption": "架構", "page": 3},
    ])])
    blocks = generate_note("codex", tmp_path, "摘要", FIGS, run=run)
    assert [b.type for b in blocks] == ["heading", "chart", "figure"]
    assert blocks[0].id != "dup"
    assert blocks[1].verified is False
    assert "p3-1.png" in run.prompts[0] and "摘要" in run.prompts[0]
    assert run.engines == ["codex"]


@pytest.mark.parametrize("bad", [
    {"reply": "ok", "blocks_json": "not json"},
    blocks_out([{"type": "chart", "spec": {"data": {}}, "source": ""}]),
    blocks_out([{"type": "figure", "path": "made-up.png", "page": 1}]),
    blocks_out([]),
    {"reply": "ok"},
])
def test_generate_note_retries_once_then_succeeds(tmp_path, bad):
    run = FakeRun([bad, blocks_out([{"type": "paragraph", "text": "好"}])])
    blocks = generate_note("claude", tmp_path, "摘要", FIGS, run=run)
    assert blocks[0].text == "好"
    assert len(run.prompts) == 2
    assert "上一次的輸出格式有誤" in run.prompts[1]


def test_generate_note_fails_after_two_bad_outputs(tmp_path):
    bad = {"reply": "ok", "blocks_json": "[{]"}
    with pytest.raises(AIFormatError) as ei:
        generate_note("claude", tmp_path, "摘要", FIGS, run=FakeRun([bad, bad]))
    assert "[{]" in ei.value.raw


def test_runner_error_propagates_without_retry(tmp_path):
    run = FakeRun([AIError("claude 超過 300 秒未完成，已中止")])
    with pytest.raises(AIError, match="300"):
        generate_note("claude", tmp_path, "摘要", FIGS, run=run)
    assert len(run.prompts) == 1


def _edit(run, **kw):
    args = dict(engine="claude", paper_dir=kw.pop("paper_dir"), summary="摘要",
                selected=[{"id": "p1", "type": "paragraph", "text": "原文"}],
                selected_text="這一句", before={"id": "h", "type": "heading", "level": 2, "text": "方法"},
                after=None, message="改白話一點", figures=["p3-1.png"], run=run)
    args.update(kw)
    return edit_selection(**args)


def test_edit_replace(tmp_path):
    run = FakeRun([blocks_out([{"type": "paragraph", "text": "新文"}], reply="已改寫")])
    res = _edit(run, paper_dir=tmp_path)
    assert res.reply == "已改寫" and res.replace[0].text == "新文"
    p = run.prompts[0]
    assert "改白話一點" in p and "這一句" in p and "原文" in p and "方法" in p


def test_edit_reply_only(tmp_path):
    res = _edit(FakeRun([{"reply": "這是在說…", "blocks_json": ""}]), paper_dir=tmp_path)
    assert res.replace is None and res.reply == "這是在說…"


def test_edit_inside_column_rejects_columns_then_retries(tmp_path):
    cols = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]}]}
    run = FakeRun([blocks_out([cols]), blocks_out([{"type": "paragraph", "text": "ok"}])])
    res = _edit(run, paper_dir=tmp_path, allow_columns=False)
    assert res.replace[0].type == "paragraph"
    assert "並排欄位內" in run.prompts[0] and "上一次的輸出格式有誤" in run.prompts[1]
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_ai_tasks.py -q`
Expected: FAIL（`No module named 'paper_notes.ai_tasks'`）

- [ ] **Step 4: 實作**

`backend/paper_notes/ai_tasks.py`：
```python
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
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_ai_tasks.py -q`
Expected: 全數 passed（13 passed）

- [ ] **Step 6: Commit**

```bash
git add backend && git commit -m "feat(backend): AI tasks with schema validation and single retry"
```

---

### Task 6: FastAPI 路由

**Files:**
- Create: `backend/paper_notes/api.py`
- Create: `backend/paper_notes/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1–5 全部
- Produces（HTTP，前端依賴這些路徑與形狀）：
  - `GET /api/health` → `{"claude": {ok, detail, fix?}, "codex": {...}}`
  - `GET /api/papers` → `[{slug, title, created, has_note}]`
  - `POST /api/papers`（multipart：`file`、`title`、`engine`）→ `{slug, job_id}`；非 PDF 回 400，超過 50MB 回 413
  - `GET /api/jobs/{job_id}` → `{status: "running"|"done"|"error", step, error, slug}`
  - `GET /api/papers/{slug}/note` → Note；`PUT` 同路徑 body Note → `{"ok": true}`（不合 schema 回 422）
  - `GET /api/papers/{slug}/figures` → `["p1-1.png", "page-1.png", ...]`
  - `GET /api/papers/{slug}/figures/{name}` → PNG
  - `GET /api/papers/{slug}/chat` → `[{role, text, ts, ...}]`
  - `POST /api/papers/{slug}/edit` body `{engine, message, block_ids, selected_text}` → `{reply, replace: [Block] | null, snapshot: str | null}`；AI 失敗回 502，detail 為 `{message, raw}`；同篇已有修改進行中回 409；區塊 id 不存在回 400。**本端點不寫 note.json**（前端套用後自動存檔），只在有 replace 時先建快照。
  - `POST /api/papers/{slug}/restore` body `{snapshot}` → Note
  - `create_app(data_dir: Path, run=ai_runner.run, check=ai_runner.check_engine) -> FastAPI`
  - `paper_notes.main:app`（讀 `PAPER_NOTES_DATA`，預設 `<repo>/papers`）

- [ ] **Step 1: 寫失敗的測試**

`backend/tests/test_api.py`：
```python
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRun
from make_sample_pdf import make_sample_pdf
from paper_notes.api import create_app

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]}}
SUMMARY = {"summary_md": "# 摘要\n" + "重點。" * 30}
NOTE_BLOCKS = [
    {"type": "heading", "level": 1, "text": "Sample"},
    {"type": "paragraph", "text": "原始段落"},
    {"type": "chart", "spec": BAR, "source": "Table 1, p.1"},
]


def blocks_out(blocks, reply="ok"):
    return {"reply": reply, "blocks_json": json.dumps(blocks, ensure_ascii=False)}


@pytest.fixture
def pdf_bytes(tmp_path):
    return make_sample_pdf(tmp_path / "s.pdf").read_bytes()


def make_client(tmp_path, outputs):
    run = FakeRun(outputs)
    check = lambda engine: {"ok": True, "detail": f"{engine} ok"}
    return TestClient(create_app(tmp_path / "data", run=run, check=check)), run


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job 未在時限內結束")


def imported(tmp_path, pdf_bytes, extra_outputs=()):
    client, run = make_client(tmp_path, [SUMMARY, blocks_out(NOTE_BLOCKS), *extra_outputs])
    res = client.post("/api/papers", files={"file": ("s.pdf", pdf_bytes, "application/pdf")},
                      data={"title": "Sample", "engine": "claude"})
    assert res.status_code == 200
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    return client, run, res.json()["slug"]


def test_health(tmp_path):
    client, _ = make_client(tmp_path, [])
    assert client.get("/api/health").json() == {
        "claude": {"ok": True, "detail": "claude ok"}, "codex": {"ok": True, "detail": "codex ok"}}


def test_upload_rejects_non_pdf(tmp_path):
    client, _ = make_client(tmp_path, [])
    res = client.post("/api/papers", files={"file": ("a.txt", b"hello", "text/plain")})
    assert res.status_code == 400 and "PDF" in res.json()["detail"]


def test_import_flow(tmp_path, pdf_bytes):
    client, run, slug = imported(tmp_path, pdf_bytes)
    note = client.get(f"/api/papers/{slug}/note").json()
    assert [b["type"] for b in note["blocks"]] == ["heading", "paragraph", "chart"]
    assert note["blocks"][2]["verified"] is False
    figures = client.get(f"/api/papers/{slug}/figures").json()
    assert "p1-1.png" in figures and "page-2.png" in figures
    img = client.get(f"/api/papers/{slug}/figures/page-1.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get("/api/papers").json()[0]["has_note"] is True
    assert "page-1.png" in run.prompts[1]


def test_import_ai_error_marks_job_error(tmp_path, pdf_bytes):
    from paper_notes.ai_runner import AIError
    client, _ = make_client(tmp_path, [AIError("claude 未登入")])
    res = client.post("/api/papers", files={"file": ("s.pdf", pdf_bytes, "application/pdf")})
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "error" and "未登入" in job["error"]


def test_import_corrupt_pdf_marks_job_error(tmp_path):
    client, _ = make_client(tmp_path, [])
    res = client.post("/api/papers", files={"file": ("b.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "error" and "PDF" in job["error"]


def test_note_get_put(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    note = client.get(f"/api/papers/{slug}/note").json()
    note["blocks"][1]["text"] = "手動修改"
    assert client.put(f"/api/papers/{slug}/note", json=note).json() == {"ok": True}
    assert client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["text"] == "手動修改"
    bad = {"blocks": [{"type": "chart", "spec": {}, "source": ""}]}
    assert client.put(f"/api/papers/{slug}/note", json=bad).status_code == 422


def test_unknown_slug_and_bad_figure_404(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    assert client.get("/api/papers/nope-000000/note").status_code == 404
    assert client.get(f"/api/papers/{slug}/figures/..%2Fpaper.pdf").status_code == 404


def test_edit_replace_creates_snapshot_and_chat(tmp_path, pdf_bytes):
    client, run, slug = imported(tmp_path, pdf_bytes,
                                 [blocks_out([{"type": "paragraph", "text": "新段落"}], reply="已改寫")])
    before = client.get(f"/api/papers/{slug}/note").json()
    pid = before["blocks"][1]["id"]
    res = client.post(f"/api/papers/{slug}/edit", json={
        "engine": "claude", "message": "改白話", "block_ids": [pid], "selected_text": "原始"})
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "已改寫" and body["replace"][0]["text"] == "新段落"
    assert body["snapshot"]
    assert client.get(f"/api/papers/{slug}/note").json() == before, "edit 端點不可寫 note.json"
    assert "Sample" in run.prompts[2], "前一個區塊應作為上下文"
    roles = [c["role"] for c in client.get(f"/api/papers/{slug}/chat").json()]
    assert roles == ["user", "assistant"]


def test_edit_reply_only_has_no_snapshot(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes, [{"reply": "這段在說…", "blocks_json": ""}])
    pid = client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["id"]
    body = client.post(f"/api/papers/{slug}/edit",
                       json={"message": "這是什麼意思？", "block_ids": [pid]}).json()
    assert body == {"reply": "這段在說…", "replace": None, "snapshot": None}


def test_edit_format_error_returns_502_and_logs(tmp_path, pdf_bytes):
    bad = {"reply": "x", "blocks_json": "[{]"}
    client, _, slug = imported(tmp_path, pdf_bytes, [bad, bad])
    before = client.get(f"/api/papers/{slug}/note").json()
    pid = before["blocks"][1]["id"]
    res = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": [pid]})
    assert res.status_code == 502
    assert "格式錯誤" in res.json()["detail"]["message"] and "[{]" in res.json()["detail"]["raw"]
    assert client.get(f"/api/papers/{slug}/note").json() == before
    assert client.get(f"/api/papers/{slug}/chat").json()[-1]["role"] == "error"


def test_edit_unknown_block_400(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    res = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": ["nope"]})
    assert res.status_code == 400


def test_edit_inside_columns_disallows_columns(tmp_path, pdf_bytes):
    cols = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]}]}
    client, run, slug = imported(tmp_path, pdf_bytes,
                                 [blocks_out([cols]), blocks_out([{"type": "paragraph", "text": "ok"}])])
    note = client.get(f"/api/papers/{slug}/note").json()
    note["blocks"].append({"id": "cc", "type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"id": "left", "type": "paragraph", "text": "L"}]},
        {"widthPct": 50, "blocks": [{"id": "right", "type": "paragraph", "text": "R"}]}]})
    client.put(f"/api/papers/{slug}/note", json=note)
    body = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": ["left"]}).json()
    assert body["replace"][0]["type"] == "paragraph"
    assert "並排欄位內" in run.prompts[2]


def test_concurrent_edit_returns_409(tmp_path, pdf_bytes):
    gate = threading.Event()
    entered = threading.Event()
    client, run, slug = imported(tmp_path, pdf_bytes)

    def slow(*args, **kwargs):
        entered.set()
        gate.wait(5)
        return {"reply": "慢", "blocks_json": ""}

    client.app.state.run_override = slow
    pid = client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["id"]
    results = {}
    t = threading.Thread(target=lambda: results.update(
        first=client.post(f"/api/papers/{slug}/edit", json={"message": "a", "block_ids": [pid]})))
    t.start()
    assert entered.wait(5)
    second = client.post(f"/api/papers/{slug}/edit", json={"message": "b", "block_ids": [pid]})
    gate.set()
    t.join(5)
    assert second.status_code == 409
    assert results["first"].status_code == 200


def test_restore(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes,
                               [blocks_out([{"type": "paragraph", "text": "新"}])])
    original = client.get(f"/api/papers/{slug}/note").json()
    pid = original["blocks"][1]["id"]
    snap = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": [pid]}).json()["snapshot"]
    changed = json.loads(json.dumps(original))
    changed["blocks"][1]["text"] = "前端套用後的新內容"
    client.put(f"/api/papers/{slug}/note", json=changed)
    assert client.post(f"/api/papers/{slug}/restore", json={"snapshot": snap}).json() == original
    assert client.post(f"/api/papers/{slug}/restore", json={"snapshot": "../x"}).status_code == 404
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_api.py -q`
Expected: FAIL（`No module named 'paper_notes.api'`）

- [ ] **Step 3: 實作**

`backend/paper_notes/api.py`：
```python
"""FastAPI 路由。create_app 可注入 run／check，測試不碰真 AI。"""
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import ai_runner, ai_tasks, pdf_service
from .schema import Note, flatten
from .storage import NotFound, Storage

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "papers"
MAX_PDF_BYTES = 50 * 1024 * 1024


class EditRequest(BaseModel):
    engine: ai_runner.Engine = "claude"
    message: str = Field(min_length=1)
    block_ids: list[str] = Field(min_length=1)
    selected_text: str = ""


class RestoreRequest(BaseModel):
    snapshot: str


def create_app(data_dir: Path, run=ai_runner.run, check=ai_runner.check_engine) -> FastAPI:
    storage = Storage(data_dir)
    app = FastAPI(title="Paper Notes")
    app.state.run_override = None  # 測試可替換 AI 呼叫
    jobs: dict[str, dict] = {}
    busy: set[str] = set()
    lock = threading.Lock()

    def ai_run(*args, **kwargs):
        return (app.state.run_override or run)(*args, **kwargs)

    def not_found(e: NotFound):
        return HTTPException(404, f"找不到：{e}")

    @app.get("/api/health")
    def health():
        return {engine: check(engine) for engine in ("claude", "codex")}

    @app.get("/api/papers")
    def list_papers():
        return [asdict(p) for p in storage.list_papers()]

    @app.post("/api/papers")
    async def upload(file: UploadFile = File(...), title: str = Form(""),
                     engine: ai_runner.Engine = Form("claude")):
        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "檔案不是 PDF")
        if len(data) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF 超過 50MB")
        slug = storage.create_paper(title.strip() or Path(file.filename or "paper").stem, data)
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"status": "running", "step": "擷取圖片", "error": None, "slug": slug}
        threading.Thread(target=import_job, args=(job_id, slug, engine), daemon=True).start()
        return {"slug": slug, "job_id": job_id}

    def import_job(job_id: str, slug: str, engine: str):
        job = jobs[job_id]
        try:
            d = storage.paper_dir(slug)
            figures = pdf_service.extract_figures(d / "paper.pdf", d / "figures")
            job["step"] = "產生摘要"
            summary = ai_tasks.generate_summary(engine, d, run=ai_run)
            storage.write_summary(slug, summary)
            job["step"] = "產生筆記"
            blocks = ai_tasks.generate_note(engine, d, summary, figures, run=ai_run)
            storage.write_note(slug, Note(blocks=blocks))
            job.update(status="done", step="完成")
        except Exception as e:  # 任何錯誤都要讓 job 結束，不能卡在 running
            job.update(status="error", error=str(e))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "找不到這個工作")
        return jobs[job_id]

    @app.get("/api/papers/{slug}/note")
    def get_note(slug: str):
        try:
            return storage.read_note(slug).model_dump(exclude_none=True)
        except NotFound as e:
            raise not_found(e)

    @app.put("/api/papers/{slug}/note")
    def put_note(slug: str, note: Note):
        try:
            storage.write_note(slug, note)
        except NotFound as e:
            raise not_found(e)
        return {"ok": True}

    @app.get("/api/papers/{slug}/figures")
    def list_figures(slug: str):
        try:
            return sorted(p.name for p in storage.figures_dir(slug).glob("*.png"))
        except NotFound as e:
            raise not_found(e)

    @app.get("/api/papers/{slug}/figures/{name}")
    def get_figure(slug: str, name: str):
        try:
            return FileResponse(storage.figure_path(slug, name), media_type="image/png")
        except NotFound as e:
            raise not_found(e)

    @app.get("/api/papers/{slug}/chat")
    def get_chat(slug: str):
        try:
            return storage.read_chat(slug)
        except NotFound as e:
            raise not_found(e)

    @app.post("/api/papers/{slug}/edit")
    def edit(slug: str, req: EditRequest):
        with lock:
            if slug in busy:
                raise HTTPException(409, "這篇筆記已有一個 AI 修改進行中，請稍候")
            busy.add(slug)
        try:
            return _edit(slug, req)
        except NotFound as e:
            raise not_found(e)
        finally:
            with lock:
                busy.discard(slug)

    def _edit(slug: str, req: EditRequest):
        note = storage.read_note(slug)
        flat = flatten(note.blocks)
        ids = [b.id for b in flat]
        missing = [i for i in req.block_ids if i not in ids]
        if missing:
            raise HTTPException(400, f"找不到區塊：{missing}")
        idx = sorted(ids.index(i) for i in req.block_ids)
        selected = [flat[i] for i in idx]
        before = flat[idx[0] - 1] if idx[0] > 0 else None
        after = flat[idx[-1] + 1] if idx[-1] + 1 < len(flat) else None
        in_columns = {leaf.id for b in note.blocks if b.type == "columns"
                      for col in b.columns for leaf in col.blocks}
        d = storage.paper_dir(slug)
        dump = lambda b: b.model_dump(exclude_none=True) if b is not None else None
        storage.append_chat(slug, {"role": "user", "text": req.message, "engine": req.engine,
                                   "block_ids": req.block_ids, "selected_text": req.selected_text})
        try:
            result = ai_tasks.edit_selection(
                req.engine, d, storage.read_summary(slug), [dump(b) for b in selected],
                req.selected_text, dump(before), dump(after), req.message,
                sorted(p.name for p in (d / "figures").glob("*.png")),
                allow_columns=not any(i in in_columns for i in req.block_ids), run=ai_run)
        except ai_runner.AIError as e:
            raw = getattr(e, "raw", None)
            storage.append_chat(slug, {"role": "error", "text": str(e), "raw": raw})
            raise HTTPException(502, {"message": str(e), "raw": raw})
        snapshot = storage.snapshot(slug) if result.replace is not None else None
        replace = [dump(b) for b in result.replace] if result.replace is not None else None
        storage.append_chat(slug, {"role": "assistant", "text": result.reply, "engine": req.engine,
                                   "snapshot": snapshot})
        return {"reply": result.reply, "replace": replace, "snapshot": snapshot}

    @app.post("/api/papers/{slug}/restore")
    def restore(slug: str, req: RestoreRequest):
        try:
            return storage.restore(slug, req.snapshot).model_dump(exclude_none=True)
        except NotFound as e:
            raise not_found(e)

    return app
```

`backend/paper_notes/main.py`：
```python
import os
from pathlib import Path

from .api import DEFAULT_DATA, create_app

app = create_app(Path(os.environ.get("PAPER_NOTES_DATA", DEFAULT_DATA)))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_api.py -q`
Expected: 全數 passed（14 passed）。`test_concurrent_edit_returns_409` 用 `app.state.run_override = slow` 接手 AI 呼叫，讓第一個請求停在 AI 階段。

- [ ] **Step 5: 跑整個後端測試套件**

Run: `.venv/bin/pytest -q`
Expected: 全數 passed，0 failed

- [ ] **Step 6: Commit**

```bash
git add backend && git commit -m "feat(backend): FastAPI routes for import, note, edit, restore"
```

---

### Task 7: 前端骨架、API client、論文列表與登入燈號

**Files:**
- Create: `frontend/package.json`、`frontend/tsconfig.json`、`frontend/vite.config.ts`、`frontend/index.html`
- Create: `frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/styles.css`
- Create: `frontend/src/types.ts`、`frontend/src/api.ts`
- Create: `frontend/src/pages/PaperList.tsx`、`frontend/src/HealthLight.tsx`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: Task 6 的 HTTP 端點
- Produces:
  - `types.ts`：`Align`、`Layout`、`LeafBlock`、`Column`、`NoteBlock`、`Note`、`PaperInfo`、`EngineHealth`、`Job`、`ChatEntry`、`Engine`、`EditResponse`
  - `api.ts`：`class ApiError(message, status, raw?)`；`api.health()`、`api.papers()`、`api.upload(file, title, engine)`、`api.job(id)`、`api.note(slug)`、`api.saveNote(slug, note)`、`api.figures(slug)`、`api.figureUrl(slug, name)`、`api.chat(slug)`、`api.edit(slug, body)`、`api.restore(slug, snapshot)`
  - 路由：`#/` 論文列表；`#/paper/<slug>` 筆記頁（Task 10 加入）

- [ ] **Step 1: 建立專案檔並安裝依賴**

`frontend/package.json`：
```json
{
  "name": "paper-notes-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run",
    "e2e": "playwright test"
  }
}
```

Run：
```bash
cd ~/projects/paper-notes/frontend
npm install react@19 react-dom@19 \
  @blocknote/core@0.55.0 @blocknote/react@0.55.0 @blocknote/mantine@0.55.0 @blocknote/xl-multi-column@0.55.0 \
  @mantine/core@^8.3.11 @mantine/hooks@^8.3.11 \
  vega vega-lite vega-embed mermaid @excalidraw/excalidraw
npm install -D typescript vite @vitejs/plugin-react vitest jsdom \
  @types/react @types/react-dom @testing-library/react @playwright/test
```
Expected：無 `ERESOLVE` 錯誤。

`frontend/tsconfig.json`：
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "types": ["vite/client"]
  },
  "include": ["src", "e2e", "vite.config.ts", "playwright.config.ts"]
}
```

`frontend/vite.config.ts`：
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`frontend/index.html`：
```html
<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Paper Notes</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/main.tsx`：
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`frontend/src/styles.css`（本檔一次寫齊所有 Task 用到的樣式）：
```css
:root {
  --bg: #fafaf8; --panel: #ffffff; --line: #e4e2dc; --text: #24231f; --muted: #6f6d66;
  --accent: #2f6fdf; --warn-bg: #fff4c7; --warn: #8a6a00; --err: #b3261e; --eli5: #eef6ee;
  font-family: system-ui, -apple-system, "PingFang TC", "Noto Sans TC", sans-serif;
  color: var(--text); background: var(--bg);
}
* { box-sizing: border-box; }
body { margin: 0; }
button { font: inherit; cursor: pointer; }
.app-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 20px; border-bottom: 1px solid var(--line); background: var(--panel); }
.app-header a { color: inherit; text-decoration: none; font-weight: 600; }
.health { display: flex; gap: 12px; font-size: 13px; color: var(--muted); }
.health-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; }
.health-dot.ok { background: #2e9d4f; } .health-dot.bad { background: var(--err); }
.paper-list { max-width: 760px; margin: 32px auto; padding: 0 16px; }
.upload-form { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); margin-bottom: 24px; }
.paper-item { display: block; padding: 12px 16px; border: 1px solid var(--line); border-radius: 8px; margin-bottom: 8px; background: var(--panel); color: inherit; text-decoration: none; }
.paper-item small { color: var(--muted); }
.job-status { color: var(--muted); } .job-error { color: var(--err); }
.paper-view { display: grid; grid-template-columns: minmax(0, 1fr) 360px; height: calc(100vh - 49px); }
.note-pane { overflow: auto; padding: 24px 0; }
.banner-error { margin: 0 24px 12px; padding: 8px 12px; background: #fde8e7; color: var(--err); border-radius: 6px; }
.eli5 { display: flex; gap: 10px; background: var(--eli5); border-radius: 8px; padding: 10px 12px; width: 100%; }
.eli5-label { flex: none; font-size: 12px; font-weight: 600; color: #2e7d32; padding-top: 2px; }
.eli5-text { flex: 1; }
.frame { border: 1px solid transparent; border-radius: 6px; }
.frame:hover { border-color: var(--line); }
.frame-toolbar { position: absolute; top: -30px; right: 0; display: none; gap: 4px; z-index: 5; }
.frame:hover .frame-toolbar { display: flex; }
.frame-toolbar button { font-size: 12px; padding: 2px 6px; border: 1px solid var(--line); background: var(--panel); border-radius: 4px; }
.frame-toolbar button.active { border-color: var(--accent); color: var(--accent); }
.frame-body { width: 100%; height: 100%; overflow: hidden; }
.frame-resize { position: absolute; right: -6px; bottom: -6px; width: 14px; height: 14px; border-radius: 3px; background: var(--accent); cursor: nwse-resize; opacity: 0; }
.frame:hover .frame-resize { opacity: 0.8; }
.frame-gap { position: absolute; left: 0; right: 0; bottom: -10px; height: 6px; cursor: ns-resize; }
.frame:hover .frame-gap { background: repeating-linear-gradient(90deg, var(--accent) 0 6px, transparent 6px 12px); opacity: 0.5; }
.chart-canvas, .diagram-canvas { width: 100%; height: 100%; }
.diagram-canvas svg { width: 100%; height: 100%; max-width: none !important; }
.chart-source { font-size: 12px; color: var(--muted); margin-top: 4px; }
.badge-unverified { position: absolute; left: 6px; top: 6px; z-index: 4; font-size: 12px; background: var(--warn-bg); color: var(--warn); border: 1px solid #e9d27a; border-radius: 4px; padding: 1px 6px; }
.block-error { color: var(--err); font-size: 13px; white-space: pre-wrap; }
.spec-editor { width: 100%; height: calc(100% - 36px); font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
.figure-img { width: 100%; height: 100%; object-fit: contain; display: block; }
.figure-caption { width: 100%; border: none; border-top: 1px dashed var(--line); padding: 4px; font-size: 13px; color: var(--muted); background: transparent; }
.figure-picker { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; max-height: 360px; overflow: auto; }
.figure-picker button { border: 1px solid var(--line); background: var(--panel); padding: 4px; border-radius: 4px; }
.figure-picker img { width: 100%; height: 90px; object-fit: contain; }
.figure-picker span { font-size: 11px; color: var(--muted); }
.whiteboard { width: 100%; height: 100%; }
.ai-flash { animation: ai-flash 2s ease-out; }
@keyframes ai-flash { from { background: #dbe8ff; } to { background: transparent; } }
.chat-panel { display: flex; flex-direction: column; border-left: 1px solid var(--line); background: var(--panel); min-height: 0; }
.chat-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line); font-weight: 600; }
.chat-log { flex: 1; overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.chat-msg { padding: 8px 10px; border-radius: 8px; font-size: 14px; white-space: pre-wrap; }
.chat-user { background: #e8f0fe; align-self: flex-end; max-width: 90%; }
.chat-assistant { background: #f3f2ee; }
.chat-error { background: #fde8e7; color: var(--err); }
.chat-pending { color: var(--muted); font-style: italic; }
.chat-restore { margin-top: 6px; font-size: 12px; border: 1px solid var(--line); background: var(--panel); border-radius: 4px; }
.chat-selection { padding: 8px 12px; font-size: 13px; color: var(--muted); border-top: 1px solid var(--line); }
.chat-input { display: grid; gap: 6px; padding: 0 12px 12px; }
.chat-input textarea { min-height: 72px; resize: vertical; font: inherit; padding: 8px; }
```

- [ ] **Step 2: 寫 types.ts 與失敗的 api 測試**

`frontend/src/types.ts`：
```ts
export type Align = "left" | "center" | "right";
export type Engine = "claude" | "codex";

export interface Layout {
  widthPct: number;
  heightPx?: number;
  marginTopPx: number;
  marginBottomPx: number;
  align: Align;
}

interface Base {
  id: string;
  layout?: Layout;
}

export type LeafBlock =
  | (Base & { type: "heading"; level: 1 | 2 | 3; text: string })
  | (Base & { type: "paragraph"; text: string })
  | (Base & { type: "eli5"; text: string })
  | (Base & { type: "chart"; spec: Record<string, unknown>; source: string; verified: boolean })
  | (Base & { type: "diagram"; mermaid: string })
  | (Base & { type: "figure"; path: string; caption: string; page: number })
  | (Base & { type: "whiteboard"; scene: Record<string, unknown> });

export interface Column {
  widthPct: number;
  blocks: LeafBlock[];
}

export type NoteBlock = LeafBlock | (Base & { type: "columns"; columns: Column[] });

export interface Note {
  blocks: NoteBlock[];
}

export interface PaperInfo {
  slug: string;
  title: string;
  created: number;
  has_note: boolean;
}

export interface EngineHealth {
  ok: boolean;
  detail: string;
  fix?: string;
}

export interface Job {
  status: "running" | "done" | "error";
  step: string;
  error: string | null;
  slug: string;
}

export interface ChatEntry {
  role: "user" | "assistant" | "error";
  text: string;
  engine?: Engine;
  snapshot?: string | null;
  raw?: string | null;
  ts: number;
}

export interface EditResponse {
  reply: string;
  replace: NoteBlock[] | null;
  snapshot: string | null;
}
```

`frontend/src/api.test.ts`：
```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("回傳 JSON", async () => {
    mockFetch(200, [{ slug: "a", title: "A", created: 1, has_note: true }]);
    expect((await api.papers())[0].slug).toBe("a");
  });

  it("字串 detail 變成錯誤訊息", async () => {
    mockFetch(409, { detail: "已有一個 AI 修改進行中" });
    await expect(api.chat("a")).rejects.toMatchObject({ message: "已有一個 AI 修改進行中", status: 409 });
  });

  it("502 的 {message, raw} detail 帶出 raw", async () => {
    mockFetch(502, { detail: { message: "AI 回傳格式錯誤", raw: "[{]" } });
    const err = await api
      .edit("a", { engine: "claude", message: "m", block_ids: ["x"], selected_text: "" })
      .catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("AI 回傳格式錯誤");
    expect(err.raw).toBe("[{]");
  });

  it("PUT note 送 JSON", async () => {
    const fn = mockFetch(200, { ok: true });
    await api.saveNote("a", { blocks: [] });
    expect(fn).toHaveBeenCalledWith("/api/papers/a/note", expect.objectContaining({ method: "PUT" }));
  });

  it("figureUrl 會編碼檔名", () => {
    expect(api.figureUrl("a", "p1-1.png")).toBe("/api/papers/a/figures/p1-1.png");
  });
});
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd ~/projects/paper-notes/frontend && npx vitest run src/api.test.ts`
Expected: FAIL（`Failed to resolve import "./api"`）

- [ ] **Step 4: 實作 api.ts**

`frontend/src/api.ts`：
```ts
import type { ChatEntry, EditResponse, Engine, EngineHealth, Job, Note, PaperInfo } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number, public raw?: string | null) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let raw: string | null = null;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && "message" in detail) {
        message = String(detail.message);
        raw = detail.raw ?? null;
      } else if (detail) message = JSON.stringify(detail);
    } catch {
      /* 非 JSON 回應，保留 HTTP 狀態訊息 */
    }
    throw new ApiError(message, res.status, raw);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => req<Record<Engine, EngineHealth>>("/api/health"),
  papers: () => req<PaperInfo[]>("/api/papers"),
  upload: (file: File, title: string, engine: Engine) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("engine", engine);
    return req<{ slug: string; job_id: string }>("/api/papers", { method: "POST", body: fd });
  },
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  note: (slug: string) => req<Note>(`/api/papers/${slug}/note`),
  saveNote: (slug: string, note: Note) => req<{ ok: boolean }>(`/api/papers/${slug}/note`, json("PUT", note)),
  figures: (slug: string) => req<string[]>(`/api/papers/${slug}/figures`),
  figureUrl: (slug: string, name: string) => `/api/papers/${slug}/figures/${encodeURIComponent(name)}`,
  chat: (slug: string) => req<ChatEntry[]>(`/api/papers/${slug}/chat`),
  edit: (slug: string, body: { engine: Engine; message: string; block_ids: string[]; selected_text: string }) =>
    req<EditResponse>(`/api/papers/${slug}/edit`, json("POST", body)),
  restore: (slug: string, snapshot: string) => req<Note>(`/api/papers/${slug}/restore`, json("POST", { snapshot })),
};
```

- [ ] **Step 5: 跑測試確認通過**

Run: `npx vitest run src/api.test.ts`
Expected: `5 passed`

- [ ] **Step 6: 實作列表頁、燈號與 App**

`frontend/src/HealthLight.tsx`：
```tsx
import { useEffect, useState } from "react";
import { api } from "./api";
import type { Engine, EngineHealth } from "./types";

export function HealthLight() {
  const [health, setHealth] = useState<Record<Engine, EngineHealth> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);
  if (error) return <span className="health"><span className="health-dot bad" />後端未啟動：{error}</span>;
  if (!health) return <span className="health">檢查 AI 狀態中…</span>;
  return (
    <span className="health">
      {(Object.keys(health) as Engine[]).map((engine) => {
        const h = health[engine];
        return (
          <span key={engine} title={h.ok ? h.detail : `${h.detail}；修復：${h.fix ?? ""}`}>
            <span className={`health-dot ${h.ok ? "ok" : "bad"}`} />
            {engine === "claude" ? "Claude" : "Codex"}
            {!h.ok && `（${h.detail}）`}
          </span>
        );
      })}
    </span>
  );
}
```

`frontend/src/pages/PaperList.tsx`：
```tsx
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Engine, PaperInfo } from "../types";

export function PaperList() {
  const [papers, setPapers] = useState<PaperInfo[]>([]);
  const [title, setTitle] = useState("");
  const [engine, setEngine] = useState<Engine>("claude");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.papers().then(setPapers).catch((e: Error) => setError(e.message));
  }, []);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("請先選擇 PDF 檔");
    setError(null);
    setStatus("上傳中…");
    try {
      const { slug, job_id } = await api.upload(file, title, engine);
      for (;;) {
        const job = await api.job(job_id);
        if (job.status === "done") {
          location.hash = `#/paper/${slug}`;
          return;
        }
        if (job.status === "error") throw new Error(job.error ?? "匯入失敗");
        setStatus(`處理中：${job.step}（整篇論文通常需要 1–3 分鐘）`);
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch (e) {
      setStatus(null);
      setError(`匯入失敗：${(e as Error).message}`);
    }
  };

  return (
    <div className="paper-list">
      <div className="upload-form">
        <strong>匯入論文</strong>
        <input ref={fileRef} type="file" accept="application/pdf" aria-label="論文 PDF" />
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="標題（可留空，用檔名）" aria-label="標題" />
        <label>
          使用 AI：
          <select value={engine} onChange={(e) => setEngine(e.target.value as Engine)}>
            <option value="claude">Claude</option>
            <option value="codex">Codex</option>
          </select>
        </label>
        <button onClick={upload} disabled={status !== null}>開始整理</button>
        {status && <span className="job-status">{status}</span>}
        {error && <span className="job-error">{error}</span>}
      </div>
      {papers.map((p) => (
        <a key={p.slug} className="paper-item" href={`#/paper/${p.slug}`}>
          {p.title}
          <br />
          <small>{new Date(p.created * 1000).toLocaleString()}{!p.has_note && " · 尚無筆記（匯入中或失敗）"}</small>
        </a>
      ))}
    </div>
  );
}
```

`frontend/src/App.tsx`：
```tsx
import { useEffect, useState } from "react";
import { HealthLight } from "./HealthLight";
import { PaperList } from "./pages/PaperList";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const onChange = () => setHash(location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  useHash();
  return (
    <>
      <header className="app-header">
        <a href="#/">Paper Notes</a>
        <HealthLight />
      </header>
      <PaperList />
    </>
  );
}
```

- [ ] **Step 7: 型別檢查與手動煙霧測試**

Run：
```bash
npx tsc --noEmit
(cd ../backend && .venv/bin/uvicorn paper_notes.main:app --port 8000 > /dev/null 2>&1 &)
(npx vite --port 5173 > /dev/null 2>&1 &)
sleep 4 && curl -s http://127.0.0.1:5173/api/health
pkill -f "uvicorn paper_notes"; pkill -f vite
```
Expected：`tsc` 無錯誤；`curl` 印出含 `"claude"` 與 `"codex"` 的 JSON（經 Vite proxy 打到後端）。

- [ ] **Step 8: Commit**

```bash
cd ~/projects/paper-notes && git add frontend && git commit -m "feat(frontend): scaffold, API client, paper list and health light"
```

---

### Task 8: note.json ↔ BlockNote 轉換

**Files:**
- Create: `frontend/src/convert/inline.ts`
- Create: `frontend/src/convert/note.ts`
- Create: `frontend/src/convert/fixtures.ts`
- Test: `frontend/src/convert/note.test.ts`

**Interfaces:**
- Consumes: `types.ts`（Task 7）
- Produces:
  - `inline.ts`：`markdownToInline(md: string): Inline[]`、`inlineToMarkdown(content: readonly unknown[]): string`
  - `note.ts`：
    - `interface BNBlock { id?: string; type: string; props?: Record<string, unknown>; content?: unknown; children?: BNBlock[] }`
    - `DEFAULT_LAYOUT: Layout`、`DEFAULT_CHART_SPEC: Record<string, unknown>`、`DEFAULT_MERMAID: string`
    - `layoutToProps(l?: Layout)` → `{widthPct, heightPx, marginTopPx, marginBottomPx, align}`（heightPx 0 代表自動）
    - `propsToLayout(p: Record<string, unknown>): Layout`
    - `noteToEditor(note: Note): BNBlock[]`、`editorToNote(blocks: readonly BNBlock[]): Note`
  - `fixtures.ts`：`SAMPLE_NOTE: Note`（Task 9 也會用）

**轉換規則（給實作者）：**
- 文字類（heading / paragraph / eli5）沒有 layout；圖表類（chart / diagram / figure / whiteboard）的 layout 攤成 BlockNote props，等於預設值時轉回 note 會省略 `layout`。
- BlockNote props 只能是基本型別，所以 `chart.spec`、`whiteboard.scene` 存成 JSON 字串。
- `columns` ↔ BlockNote `columnList` > `column`（props `width` 為相對比例）。`widthPct = width / Σwidth × 100`，四捨五入到 0.1，最後一欄補足 100。欄 id 為 `${columnsId}-c${i}`，轉回時丟棄。
- 非空欄位數 2–3 才保留成 columns；1 欄或 >3 欄就攤平。
- BlockNote 內建但 note 沒有的區塊（列表、引言、程式碼…）降級成 paragraph（保留文字；沒文字就丟棄）。
- 巢狀 children 攤平到父區塊之後。
- 文件結尾的空 paragraph（BlockNote 會自動補一個）丟棄。
- heading level 夾到 1–3；chart spec 解析失敗或缺 mark 類欄位時用 `DEFAULT_CHART_SPEC`；figure 沒選圖（path 空）就丟棄。

- [ ] **Step 1: 寫 fixtures 與失敗的測試**

`frontend/src/convert/fixtures.ts`：
```ts
import type { Note } from "../types";

export const BAR_SPEC = {
  mark: "bar",
  data: { values: [{ x: "A", y: 1 }, { x: "B", y: 3 }] },
  encoding: { x: { field: "x", type: "nominal" }, y: { field: "y", type: "quantitative" } },
};

export const SAMPLE_NOTE: Note = {
  blocks: [
    { id: "h1", type: "heading", level: 1, text: "Attention Is All You Need" },
    { id: "p1", type: "paragraph", text: "我們提出 **Transformer**，完全使用 *attention*，見 [論文](https://arxiv.org/abs/1706.03762) 與 `softmax`。" },
    { id: "e1", type: "eli5", text: "就像開會時每個人同時聽所有人說話。" },
    { id: "c1", type: "chart", spec: BAR_SPEC, source: "Table 2, p.8", verified: false,
      layout: { widthPct: 60, heightPx: 300, marginTopPx: 8, marginBottomPx: 24, align: "left" } },
    { id: "d1", type: "diagram", mermaid: "flowchart LR\n  A[輸入] --> B[Encoder]" },
    { id: "f1", type: "figure", path: "p3-1.png", caption: "模型架構", page: 3 },
    { id: "w1", type: "whiteboard", scene: { elements: [] } },
    { id: "col", type: "columns", columns: [
      { widthPct: 40, blocks: [{ id: "cl", type: "paragraph", text: "左欄" }] },
      { widthPct: 60, blocks: [{ id: "cr", type: "eli5", text: "右欄" }] },
    ] },
  ],
};
```

`frontend/src/convert/note.test.ts`：
```ts
import { describe, expect, it } from "vitest";
import { inlineToMarkdown, markdownToInline } from "./inline";
import { DEFAULT_CHART_SPEC, editorToNote, noteToEditor, type BNBlock } from "./note";
import { SAMPLE_NOTE } from "./fixtures";

describe("inline", () => {
  it("markdown 來回轉換不失真", () => {
    const md = "我們提出 **Transformer**，完全使用 *attention*，見 [論文](https://x.org) 與 `softmax`。";
    expect(inlineToMarkdown(markdownToInline(md))).toBe(md);
  });
  it("產生 BlockNote 的 styled text 與 link", () => {
    expect(markdownToInline("a **b** [c](u)")).toEqual([
      { type: "text", text: "a ", styles: {} },
      { type: "text", text: "b", styles: { bold: true } },
      { type: "text", text: " ", styles: {} },
      { type: "link", href: "u", content: [{ type: "text", text: "c", styles: {} }] },
    ]);
  });
});

describe("note <-> editor", () => {
  it("SAMPLE_NOTE 來回轉換完全相同", () => {
    expect(editorToNote(noteToEditor(SAMPLE_NOTE))).toEqual(SAMPLE_NOTE);
  });

  it("columns 轉成 columnList，寬度用相對比例", () => {
    const col = noteToEditor(SAMPLE_NOTE).find((b) => b.type === "columnList")!;
    expect(col.children!.map((c) => [c.type, c.props!.width])).toEqual([["column", 0.8], ["column", 1.2]]);
  });

  it("欄寬比例 1:3 → 25/75", () => {
    const blocks: BNBlock[] = [{ id: "L", type: "columnList", children: [
      { id: "a", type: "column", props: { width: 1 }, children: [{ id: "x", type: "paragraph", content: [] }] },
      { id: "b", type: "column", props: { width: 3 }, children: [{ id: "y", type: "paragraph", content: [] }] },
    ] }];
    const note = editorToNote(blocks);
    expect(note.blocks[0]).toMatchObject({ type: "columns", columns: [{ widthPct: 25 }, { widthPct: 75 }] });
  });

  it("只剩一欄有內容時攤平", () => {
    const blocks: BNBlock[] = [{ id: "L", type: "columnList", children: [
      { id: "a", type: "column", props: { width: 1 }, children: [{ id: "x", type: "paragraph", content: [{ type: "text", text: "留下", styles: {} }] }] },
      { id: "b", type: "column", props: { width: 1 }, children: [] },
    ] }];
    expect(editorToNote(blocks).blocks).toEqual([{ id: "x", type: "paragraph", text: "留下" }]);
  });

  it("未知的內建區塊降級成段落，空的丟棄", () => {
    const blocks: BNBlock[] = [
      { id: "b1", type: "bulletListItem", content: [{ type: "text", text: "清單項目", styles: {} }] },
      { id: "b2", type: "codeBlock", content: [] },
    ];
    expect(editorToNote(blocks).blocks).toEqual([{ id: "b1", type: "paragraph", text: "清單項目" }]);
  });

  it("巢狀 children 攤平到父區塊之後", () => {
    const blocks: BNBlock[] = [{ id: "a", type: "paragraph", content: [{ type: "text", text: "父", styles: {} }],
      children: [{ id: "b", type: "paragraph", content: [{ type: "text", text: "子", styles: {} }] }] }];
    expect(editorToNote(blocks).blocks.map((b) => b.id)).toEqual(["a", "b"]);
  });

  it("結尾的空段落丟棄，中間的保留", () => {
    const blocks: BNBlock[] = [
      { id: "a", type: "paragraph", content: [] },
      { id: "b", type: "paragraph", content: [{ type: "text", text: "x", styles: {} }] },
      { id: "c", type: "paragraph", content: [] },
    ];
    expect(editorToNote(blocks).blocks.map((b) => b.id)).toEqual(["a", "b"]);
  });

  it("heading level 夾到 3、壞掉的 chart spec 用預設、沒選圖的 figure 丟棄", () => {
    const blocks: BNBlock[] = [
      { id: "h", type: "heading", props: { level: 5 }, content: [{ type: "text", text: "H", styles: {} }] },
      { id: "c", type: "chart", props: { spec: "{oops", source: "", verified: false, widthPct: 100, heightPx: 0, marginTopPx: 8, marginBottomPx: 8, align: "center" } },
      { id: "f", type: "figure", props: { path: "", caption: "", page: 1, widthPct: 100, heightPx: 0, marginTopPx: 8, marginBottomPx: 8, align: "center" } },
    ];
    const note = editorToNote(blocks);
    expect(note.blocks).toEqual([
      { id: "h", type: "heading", level: 3, text: "H" },
      { id: "c", type: "chart", spec: DEFAULT_CHART_SPEC, source: "", verified: false },
    ]);
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `npx vitest run src/convert`
Expected: FAIL（`Failed to resolve import "./inline"`）

- [ ] **Step 3: 實作 inline.ts**

`frontend/src/convert/inline.ts`：
```ts
export type Styles = { bold?: true; italic?: true; code?: true };
export type StyledText = { type: "text"; text: string; styles: Styles };
export type Link = { type: "link"; href: string; content: StyledText[] };
export type Inline = StyledText | Link;

const TOKEN = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g;

const text = (t: string, styles: Styles = {}): StyledText => ({ type: "text", text: t, styles });

/** 只支援粗體、斜體、行內程式碼、連結；巢狀樣式（粗斜體）不保證保留。 */
export function markdownToInline(md: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of md.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(text(md.slice(last, i)));
    if (m[1] !== undefined) out.push({ type: "link", href: m[2], content: [text(m[1])] });
    else if (m[3] !== undefined) out.push(text(m[3], { bold: true }));
    else if (m[4] !== undefined) out.push(text(m[4], { italic: true }));
    else out.push(text(m[5], { code: true }));
    last = i + m[0].length;
  }
  if (last < md.length) out.push(text(md.slice(last)));
  return out;
}

function wrap(t: string, s: Record<string, unknown>): string {
  if (!t) return t;
  if (s.code) return "`" + t + "`";
  let r = t;
  if (s.italic) r = `*${r}*`;
  if (s.bold) r = `**${r}**`;
  return r;
}

export function inlineToMarkdown(content: readonly unknown[]): string {
  return content
    .map((item) => {
      const it = item as { type?: string; text?: string; styles?: Record<string, unknown>; href?: string; content?: unknown[] };
      if (it.type === "link") return `[${inlineToMarkdown(it.content ?? [])}](${it.href ?? ""})`;
      if (it.type === "text") return wrap(it.text ?? "", it.styles ?? {});
      return "";
    })
    .join("");
}
```

- [ ] **Step 4: 實作 note.ts**

`frontend/src/convert/note.ts`：
```ts
import type { Align, Column, Layout, LeafBlock, Note, NoteBlock } from "../types";
import { inlineToMarkdown, markdownToInline } from "./inline";

export interface BNBlock {
  id?: string;
  type: string;
  props?: Record<string, unknown>;
  content?: unknown;
  children?: BNBlock[];
}

export const DEFAULT_LAYOUT: Layout = { widthPct: 100, marginTopPx: 8, marginBottomPx: 8, align: "center" };
export const DEFAULT_CHART_SPEC: Record<string, unknown> = {
  mark: "bar",
  data: { values: [{ 類別: "A", 數值: 1 }, { 類別: "B", 數值: 2 }] },
  encoding: { x: { field: "類別", type: "nominal" }, y: { field: "數值", type: "quantitative" } },
};
export const DEFAULT_MERMAID = "flowchart LR\n  A[輸入] --> B[處理] --> C[輸出]";
const VEGA_VIEW_KEYS = ["mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"];

const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const str = (v: unknown) => (typeof v === "string" ? v : "");
const round1 = (v: number) => Math.round(v * 10) / 10;

export function layoutToProps(l?: Layout) {
  const x = { ...DEFAULT_LAYOUT, ...l };
  return { widthPct: x.widthPct, heightPx: x.heightPx ?? 0, marginTopPx: x.marginTopPx, marginBottomPx: x.marginBottomPx, align: x.align };
}

export function propsToLayout(p: Record<string, unknown>): Layout {
  const align = (["left", "center", "right"].includes(p.align as string) ? p.align : "center") as Align;
  const l: Layout = { widthPct: num(p.widthPct, 100), marginTopPx: num(p.marginTopPx, 8), marginBottomPx: num(p.marginBottomPx, 8), align };
  const h = num(p.heightPx, 0);
  if (h > 0) l.heightPx = h;
  return l;
}

function isDefaultLayout(l: Layout) {
  return l.widthPct === 100 && l.heightPx === undefined && l.marginTopPx === 8 && l.marginBottomPx === 8 && l.align === "center";
}

function withLayout<T extends LeafBlock>(b: T, props: Record<string, unknown>): T {
  const layout = propsToLayout(props);
  return isDefaultLayout(layout) ? b : { ...b, layout };
}

function parseObj(v: unknown): Record<string, unknown> | null {
  try {
    const o = JSON.parse(str(v));
    return o && typeof o === "object" && !Array.isArray(o) ? o : null;
  } catch {
    return null;
  }
}

function leafToBN(b: LeafBlock): BNBlock {
  switch (b.type) {
    case "heading":
      return { id: b.id, type: "heading", props: { level: b.level }, content: markdownToInline(b.text) };
    case "paragraph":
      return { id: b.id, type: "paragraph", content: markdownToInline(b.text) };
    case "eli5":
      return { id: b.id, type: "eli5", content: markdownToInline(b.text) };
    case "chart":
      return { id: b.id, type: "chart", props: { spec: JSON.stringify(b.spec), source: b.source, verified: b.verified, ...layoutToProps(b.layout) } };
    case "diagram":
      return { id: b.id, type: "diagram", props: { mermaid: b.mermaid, ...layoutToProps(b.layout) } };
    case "figure":
      return { id: b.id, type: "figure", props: { path: b.path, caption: b.caption, page: b.page, ...layoutToProps(b.layout) } };
    case "whiteboard":
      return { id: b.id, type: "whiteboard", props: { scene: JSON.stringify(b.scene), ...layoutToProps(b.layout) } };
  }
}

export function noteToEditor(note: Note): BNBlock[] {
  return note.blocks.map((b) =>
    b.type === "columns"
      ? {
          id: b.id,
          type: "columnList",
          children: b.columns.map((c, i) => ({
            id: `${b.id}-c${i}`,
            type: "column",
            props: { width: c.widthPct / (100 / b.columns.length) },
            children: c.blocks.map(leafToBN),
          })),
        }
      : leafToBN(b),
  );
}

function bnToLeaf(b: BNBlock): LeafBlock | null {
  const p = b.props ?? {};
  const id = b.id ?? "";
  const text = Array.isArray(b.content) ? inlineToMarkdown(b.content) : "";
  switch (b.type) {
    case "heading":
      return { id, type: "heading", level: Math.min(3, Math.max(1, num(p.level, 1))) as 1 | 2 | 3, text };
    case "paragraph":
      return { id, type: "paragraph", text };
    case "eli5":
      return { id, type: "eli5", text };
    case "chart": {
      const spec = parseObj(p.spec);
      const valid = spec && VEGA_VIEW_KEYS.some((k) => k in spec);
      return withLayout({ id, type: "chart", spec: valid ? spec : DEFAULT_CHART_SPEC, source: str(p.source), verified: p.verified === true }, p);
    }
    case "diagram":
      return withLayout({ id, type: "diagram", mermaid: str(p.mermaid).trim() ? str(p.mermaid) : DEFAULT_MERMAID }, p);
    case "figure":
      if (!str(p.path)) return null;
      return withLayout({ id, type: "figure", path: str(p.path), caption: str(p.caption), page: Math.max(1, num(p.page, 1)) }, p);
    case "whiteboard":
      return withLayout({ id, type: "whiteboard", scene: parseObj(p.scene) ?? { elements: [] } }, p);
    default:
      // 其他 BlockNote 內建區塊（列表、引言、程式碼…）降級成段落，避免存檔被 schema 擋下
      return text ? { id, type: "paragraph", text } : null;
  }
}

function flattenLeaves(blocks: readonly BNBlock[]): LeafBlock[] {
  const out: LeafBlock[] = [];
  for (const b of blocks) {
    if (b.type === "columnList" || b.type === "column") {
      out.push(...flattenLeaves(b.children ?? []));
      continue;
    }
    const leaf = bnToLeaf(b);
    if (leaf) out.push(leaf);
    out.push(...flattenLeaves(b.children ?? []));
  }
  return out;
}

function toColumns(b: BNBlock): NoteBlock[] {
  const cols = (b.children ?? [])
    .filter((c) => c.type === "column")
    .map((c) => ({ width: num(c.props?.width, 1), leaves: flattenLeaves(c.children ?? []) }))
    .filter((c) => c.leaves.length > 0);
  if (cols.length < 2 || cols.length > 3) return cols.flatMap((c) => c.leaves);
  const total = cols.reduce((s, c) => s + c.width, 0);
  const widths = cols.map((c) => Math.min(90, Math.max(10, round1((c.width / total) * 100))));
  widths[widths.length - 1] = round1(100 - widths.slice(0, -1).reduce((s, w) => s + w, 0));
  const columns: Column[] = cols.map((c, i) => ({ widthPct: widths[i], blocks: c.leaves }));
  return [{ id: b.id ?? "", type: "columns", columns }];
}

export function editorToNote(blocks: readonly BNBlock[]): Note {
  const out: NoteBlock[] = [];
  for (const b of blocks) {
    if (b.type === "columnList") out.push(...toColumns(b));
    else out.push(...flattenLeaves([b]));
  }
  while (out.length > 0) {
    const last = out[out.length - 1];
    if (last.type === "paragraph" && last.text === "") out.pop();
    else break;
  }
  return { blocks: out };
}
```

- [ ] **Step 5: 跑測試確認通過**

Run: `npx vitest run src/convert`
Expected: `10 passed`

- [ ] **Step 6: Commit**

```bash
git add frontend && git commit -m "feat(frontend): lossless note.json <-> BlockNote conversion"
```

---

### Task 9: 版面拖曳與自訂區塊

**Files:**
- Create: `frontend/src/editor/layout.ts`
- Test: `frontend/src/editor/layout.test.ts`
- Create: `frontend/src/editor/slugStore.ts`
- Create: `frontend/src/editor/ResizableFrame.tsx`
- Create: `frontend/src/editor/blocks.tsx`
- Create: `frontend/src/editor/schema.ts`
- Test: `frontend/src/editor/schema.test.ts`

**Interfaces:**
- Consumes: `layoutToProps`、`propsToLayout`、`DEFAULT_CHART_SPEC`、`DEFAULT_MERMAID`（Task 8）；`api.figures`、`api.figureUrl`（Task 7）
- Produces:
  - `layout.ts`：`resizeLayout(start: Layout, dx, dy, containerWidthPx, startHeightPx): Layout`、`gapLayout(start: Layout, dy): Layout`、`frameStyle(l: Layout, defaultHeightPx: number): React.CSSProperties`
  - `slugStore.ts`：`slugStore = { current: string }`（FigureView 取 slug 用；BlockNote 區塊在 portal 中 render，不依賴 React context）
  - `ResizableFrame` 元件：props `{ layout, onChange(l), defaultHeightPx, toolbar?, children }`
  - `blocks.tsx`：`Eli5Block`、`ChartBlock`、`DiagramBlock`、`FigureBlock`、`WhiteboardBlock`（皆為 `createReactBlockSpec(...)` 回傳的工廠函式，使用時要呼叫：`ChartBlock()`）
  - `schema.ts`：`schema`（含 paragraph、heading、五個自訂區塊與多欄）

**BlockNote 0.55.0 API（2026-10-01 從 `node_modules/@blocknote/*/types` 確認）：** `createReactBlockSpec(config, impl)` 回傳 `(options?) => BlockSpec`；`withMultiColumn(schema)`；`multiColumnDropCursor` 是 `{hooks}`，傳給 `useCreateBlockNote({ dropCursor })`；`editor.replaceBlocks(ids, blocks)` 回傳 `{ insertedBlocks, removedBlocks }`；`editor.isEditable` 可設定；`editor.onSelectionChange(cb)`；`editor.getSelection()` 未選多區塊時為 `undefined`；`editor.mount(el)` 存在。若型別與此不符，以 `node_modules/@blocknote/*/types` 為準。

- [ ] **Step 1: 寫 layout 的失敗測試**

`frontend/src/editor/layout.test.ts`：
```ts
import { describe, expect, it } from "vitest";
import { frameStyle, gapLayout, resizeLayout } from "./layout";
import type { Layout } from "../types";

const L: Layout = { widthPct: 50, marginTopPx: 8, marginBottomPx: 8, align: "center" };

describe("layout", () => {
  it("向右拖 100px（容器 1000px）寬度 +10%", () => {
    expect(resizeLayout(L, 100, 0, 1000, 300)).toMatchObject({ widthPct: 60, heightPx: 300 });
  });
  it("寬度夾在 10–100%、高度夾在 50–2000px", () => {
    expect(resizeLayout(L, -2000, -1000, 1000, 300)).toMatchObject({ widthPct: 10, heightPx: 50 });
    expect(resizeLayout(L, 5000, 5000, 1000, 300)).toMatchObject({ widthPct: 100, heightPx: 2000 });
  });
  it("間距夾在 0–200px", () => {
    expect(gapLayout(L, 30).marginBottomPx).toBe(38);
    expect(gapLayout(L, -100).marginBottomPx).toBe(0);
    expect(gapLayout(L, 999).marginBottomPx).toBe(200);
  });
  it("frameStyle：對齊與預設高度", () => {
    expect(frameStyle({ ...L, align: "left" }, 320)).toMatchObject({ width: "50%", height: "320px", marginLeft: 0, marginRight: "auto" });
    expect(frameStyle({ ...L, heightPx: 200, align: "right" }, 320)).toMatchObject({ height: "200px", marginLeft: "auto", marginRight: 0 });
    expect(frameStyle(L, 0).height).toBeUndefined();
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `npx vitest run src/editor/layout.test.ts`
Expected: FAIL（`Failed to resolve import "./layout"`）

- [ ] **Step 3: 實作 layout.ts**

`frontend/src/editor/layout.ts`：
```ts
import type { CSSProperties } from "react";
import type { Layout } from "../types";

export const MIN_WIDTH_PCT = 10;
export const MIN_HEIGHT = 50;
export const MAX_HEIGHT = 2000;
export const MAX_GAP = 200;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function resizeLayout(start: Layout, dx: number, dy: number, containerWidthPx: number, startHeightPx: number): Layout {
  const startWidthPx = (containerWidthPx * start.widthPct) / 100;
  const widthPct = clamp(Math.round(((startWidthPx + dx) / containerWidthPx) * 1000) / 10, MIN_WIDTH_PCT, 100);
  const heightPx = clamp(Math.round(startHeightPx + dy), MIN_HEIGHT, MAX_HEIGHT);
  return { ...start, widthPct, heightPx };
}

export function gapLayout(start: Layout, dy: number): Layout {
  return { ...start, marginBottomPx: clamp(Math.round(start.marginBottomPx + dy), 0, MAX_GAP) };
}

export function frameStyle(l: Layout, defaultHeightPx: number): CSSProperties {
  const h = l.heightPx || defaultHeightPx;
  return {
    position: "relative",
    width: `${l.widthPct}%`,
    height: h ? `${h}px` : undefined,
    marginTop: l.marginTopPx,
    marginBottom: l.marginBottomPx,
    marginLeft: l.align === "left" ? 0 : "auto",
    marginRight: l.align === "right" ? 0 : "auto",
  };
}
```

Run: `npx vitest run src/editor/layout.test.ts`
Expected: `4 passed`

- [ ] **Step 4: 實作 slugStore 與 ResizableFrame**

`frontend/src/editor/slugStore.ts`：
```ts
/** 目前開啟的論文 slug。BlockNote 自訂區塊在 portal 中 render，用模組變數比 React context 可靠。 */
export const slugStore = { current: "" };
```

`frontend/src/editor/ResizableFrame.tsx`：
```tsx
import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { Align, Layout } from "../types";
import { frameStyle, gapLayout, resizeLayout } from "./layout";

interface Props {
  layout: Layout;
  onChange: (l: Layout) => void;
  defaultHeightPx: number;
  toolbar?: ReactNode;
  children: ReactNode;
}

const ALIGNS: [Align, string][] = [["left", "靠左"], ["center", "置中"], ["right", "靠右"]];

export function ResizableFrame({ layout, onChange, defaultHeightPx, toolbar, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Layout | null>(null); // 拖曳中的暫時版面，放開才寫回區塊（一次 undo）
  const shown = draft ?? layout;

  const startDrag = (e: ReactPointerEvent, mode: "resize" | "gap") => {
    e.preventDefault();
    e.stopPropagation();
    const el = ref.current;
    if (!el?.parentElement) return;
    const containerWidth = el.parentElement.getBoundingClientRect().width;
    const startHeight = el.getBoundingClientRect().height;
    const x0 = e.clientX;
    const y0 = e.clientY;
    let latest = layout;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      const dy = ev.clientY - y0;
      latest = mode === "resize" ? resizeLayout(layout, dx, dy, containerWidth, startHeight) : gapLayout(layout, dy);
      setDraft(latest);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDraft(null);
      onChange(latest);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={ref} className="frame" style={frameStyle(shown, defaultHeightPx)} contentEditable={false}>
      <div className="frame-toolbar">
        {toolbar}
        {layout.widthPct < 100 &&
          ALIGNS.map(([a, label]) => (
            <button key={a} className={layout.align === a ? "active" : ""} onClick={() => onChange({ ...layout, align: a })}>
              {label}
            </button>
          ))}
      </div>
      <div className="frame-body">{children}</div>
      <div className="frame-resize" title="拖曳調整大小" onPointerDown={(e) => startDrag(e, "resize")} />
      <div className="frame-gap" title="拖曳調整下方間距" onPointerDown={(e) => startDrag(e, "gap")} />
    </div>
  );
}
```

- [ ] **Step 5: 實作自訂區塊**

`frontend/src/editor/blocks.tsx`：
```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import type { BlockNoteEditor } from "@blocknote/core";
import { createReactBlockSpec } from "@blocknote/react";
import embed from "vega-embed";
import mermaid from "mermaid";
import { Excalidraw } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { api } from "../api";
import { DEFAULT_CHART_SPEC, DEFAULT_MERMAID, layoutToProps, propsToLayout } from "../convert/note";
import type { Layout } from "../types";
import { ResizableFrame } from "./ResizableFrame";
import { slugStore } from "./slugStore";

const layoutPropSchema = {
  widthPct: { default: 100 },
  heightPx: { default: 0 },
  marginTopPx: { default: 8 },
  marginBottomPx: { default: 8 },
  align: { default: "center" as const, values: ["left", "center", "right"] as const },
};

type LayoutProps = ReturnType<typeof layoutToProps>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyEditor = BlockNoteEditor<any, any, any>;
interface ViewProps<P> {
  block: { id: string; props: P };
  editor: AnyEditor;
}

function useBlockProps<P extends LayoutProps>({ block, editor }: ViewProps<P>) {
  const update = (props: Partial<P>) => editor.updateBlock(block.id, { props } as never);
  const layout = propsToLayout(block.props as unknown as Record<string, unknown>);
  const setLayout = (l: Layout) => update(layoutToProps(l) as Partial<P>);
  return { p: block.props, update, layout, setLayout };
}

/* ---------- ELI5 白話框 ---------- */
export const Eli5Block = createReactBlockSpec(
  { type: "eli5", propSchema: {}, content: "inline" },
  {
    render: (props) => (
      <div className="eli5">
        <span className="eli5-label" contentEditable={false}>白話解釋</span>
        <div className="eli5-text" ref={props.contentRef} />
      </div>
    ),
  },
);

/* ---------- 數據圖 ---------- */
type ChartProps = LayoutProps & { spec: string; source: string; verified: boolean };
const VEGA_VIEW_KEYS = ["mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"];

function prettyJson(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

function ChartView(props: ViewProps<ChartProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const ref = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(p.spec);
  const [err, setErr] = useState<string | null>(null);
  const height = layout.heightPx || 320;

  useEffect(() => {
    if (editing || !ref.current) return;
    let spec: Record<string, unknown>;
    try {
      spec = JSON.parse(p.spec);
    } catch {
      setErr("規格不是合法 JSON");
      return;
    }
    let cancelled = false;
    let finalize: (() => void) | undefined;
    embed(ref.current, { ...spec, width: "container", height: Math.max(60, height - 70), autosize: { type: "fit", contains: "padding" } } as never, { actions: false })
      .then((r) => {
        if (cancelled) r.finalize();
        else {
          finalize = r.finalize;
          setErr(null);
        }
      })
      .catch((e: Error) => setErr(`圖表無法繪製：${e.message}`));
    return () => {
      cancelled = true;
      finalize?.();
    };
  }, [p.spec, layout.widthPct, height, editing]);

  const save = () => {
    try {
      const s = JSON.parse(draft);
      if (!VEGA_VIEW_KEYS.some((k) => k in s)) throw new Error("需要 mark、layer 等其中一個欄位");
      update({ spec: JSON.stringify(s) });
      setEditing(false);
      setErr(null);
    } catch (e) {
      setErr(`無法套用：${(e as Error).message}`);
    }
  };

  return (
    <ResizableFrame
      layout={layout}
      onChange={setLayout}
      defaultHeightPx={320}
      toolbar={<button onClick={() => { setDraft(prettyJson(p.spec)); setEditing(!editing); }}>{editing ? "關閉" : "編輯資料"}</button>}
    >
      {!p.verified && (
        <button className="badge-unverified" title="對過論文原文後點擊" onClick={() => update({ verified: true })}>
          AI 抽取，待核對
        </button>
      )}
      {editing ? (
        <>
          <textarea className="spec-editor" value={draft} onChange={(e) => setDraft(e.target.value)} />
          <button onClick={save}>套用</button>
        </>
      ) : (
        <div ref={ref} className="chart-canvas" />
      )}
      {p.source && <div className="chart-source">出處：{p.source}</div>}
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const ChartBlock = createReactBlockSpec(
  {
    type: "chart",
    propSchema: { spec: { default: JSON.stringify(DEFAULT_CHART_SPEC) }, source: { default: "" }, verified: { default: false }, ...layoutPropSchema },
    content: "none",
  },
  { render: ({ block, editor }) => <ChartView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 概念圖 ---------- */
type DiagramProps = LayoutProps & { mermaid: string };
let mermaidReady = false;
let mermaidCounter = 0;

function DiagramView(props: ViewProps<DiagramProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const ref = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(p.mermaid);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (editing || !ref.current) return;
    if (!mermaidReady) {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
      mermaidReady = true;
    }
    let cancelled = false;
    const id = `mmd-${props.block.id}-${++mermaidCounter}`;
    mermaid
      .render(id, p.mermaid)
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setErr(null);
        }
      })
      .catch((e: Error) => {
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) setErr(`Mermaid 語法錯誤：${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, [p.mermaid, editing, props.block.id]);

  const save = async () => {
    try {
      await mermaid.parse(draft);
      update({ mermaid: draft });
      setEditing(false);
    } catch (e) {
      setErr(`無法套用：${(e as Error).message}`);
    }
  };

  return (
    <ResizableFrame
      layout={layout}
      onChange={setLayout}
      defaultHeightPx={0}
      toolbar={<button onClick={() => { setDraft(p.mermaid); setEditing(!editing); }}>{editing ? "關閉" : "編輯原始碼"}</button>}
    >
      {editing ? (
        <>
          <textarea className="spec-editor" style={{ minHeight: 160 }} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <button onClick={save}>套用</button>
        </>
      ) : (
        <div ref={ref} className="diagram-canvas" />
      )}
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const DiagramBlock = createReactBlockSpec(
  { type: "diagram", propSchema: { mermaid: { default: DEFAULT_MERMAID }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <DiagramView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 論文原圖 ---------- */
type FigureProps = LayoutProps & { path: string; caption: string; page: number };

function FigureView(props: ViewProps<FigureProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const [choices, setChoices] = useState<string[] | null>(null);
  const [caption, setCaption] = useState(p.caption);
  const [err, setErr] = useState<string | null>(null);
  const slug = slugStore.current;

  const openPicker = () => api.figures(slug).then(setChoices).catch((e: Error) => setErr(e.message));
  useEffect(() => {
    if (!p.path) openPicker();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.path]);
  useEffect(() => setCaption(p.caption), [p.caption]);

  const pick = (name: string) => {
    const m = name.match(/^(?:page-|p)(\d+)/);
    update({ path: name, page: m ? Number(m[1]) : 1 });
    setChoices(null);
  };

  return (
    <ResizableFrame layout={layout} onChange={setLayout} defaultHeightPx={0} toolbar={<button onClick={openPicker}>換圖</button>}>
      {choices ? (
        <div className="figure-picker">
          {choices.map((name) => (
            <button key={name} onClick={() => pick(name)}>
              <img src={api.figureUrl(slug, name)} alt={name} loading="lazy" />
              <span>{name}</span>
            </button>
          ))}
        </div>
      ) : (
        p.path && <img className="figure-img" src={api.figureUrl(slug, p.path)} alt={p.caption} />
      )}
      <input
        className="figure-caption"
        value={caption}
        placeholder="圖說"
        onChange={(e) => setCaption(e.target.value)}
        onBlur={() => caption !== p.caption && update({ caption })}
      />
      {err && <div className="block-error">{err}</div>}
    </ResizableFrame>
  );
}

export const FigureBlock = createReactBlockSpec(
  { type: "figure", propSchema: { path: { default: "" }, caption: { default: "" }, page: { default: 1 }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <FigureView block={block as never} editor={editor as AnyEditor} /> },
);

/* ---------- 白板 ---------- */
type WhiteboardProps = LayoutProps & { scene: string };

function WhiteboardView(props: ViewProps<WhiteboardProps>) {
  const { p, update, layout, setLayout } = useBlockProps(props);
  const initial = useMemo(() => {
    try {
      return JSON.parse(p.scene) as { elements?: unknown[] };
    } catch {
      return { elements: [] };
    }
    // 只在掛載時讀一次；之後由 Excalidraw 自己持有狀態
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.block.id]);
  const lastSaved = useRef(p.scene);
  const timer = useRef<number | undefined>(undefined);

  const onChange = (elements: readonly unknown[]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const next = JSON.stringify({ elements });
      if (next !== lastSaved.current) {
        lastSaved.current = next;
        update({ scene: next });
      }
    }, 800);
  };

  return (
    <ResizableFrame layout={layout} onChange={setLayout} defaultHeightPx={420}>
      <div className="whiteboard" onKeyDown={(e) => e.stopPropagation()} onPaste={(e) => e.stopPropagation()}>
        <Excalidraw initialData={{ elements: (initial.elements ?? []) as never, appState: { viewBackgroundColor: "#ffffff" } }} onChange={onChange} />
      </div>
    </ResizableFrame>
  );
}

export const WhiteboardBlock = createReactBlockSpec(
  { type: "whiteboard", propSchema: { scene: { default: '{"elements":[]}' }, ...layoutPropSchema }, content: "none" },
  { render: ({ block, editor }) => <WhiteboardView block={block as never} editor={editor as AnyEditor} /> },
);
```

> 若 `@excalidraw/excalidraw/index.css` 解析失敗：`ls node_modules/@excalidraw/excalidraw/dist/` 找實際的 CSS 檔名並改 import。

`frontend/src/editor/schema.ts`：
```ts
import { BlockNoteSchema, defaultBlockSpecs } from "@blocknote/core";
import { withMultiColumn } from "@blocknote/xl-multi-column";
import { ChartBlock, DiagramBlock, Eli5Block, FigureBlock, WhiteboardBlock } from "./blocks";

const { paragraph, heading } = defaultBlockSpecs;

/** 只開放筆記 schema 支援的區塊；斜線選單會依此自動過濾內建選項。 */
export const schema = withMultiColumn(
  BlockNoteSchema.create({
    blockSpecs: {
      paragraph,
      heading,
      eli5: Eli5Block(),
      chart: ChartBlock(),
      diagram: DiagramBlock(),
      figure: FigureBlock(),
      whiteboard: WhiteboardBlock(),
    },
  }),
);
```

- [ ] **Step 6: 寫 schema 整合測試（驗證轉換結果真的能被 BlockNote 吃進去）**

`frontend/src/editor/schema.test.ts`：
```ts
import { describe, expect, it, vi } from "vitest";

vi.mock("@excalidraw/excalidraw", () => ({ Excalidraw: () => null }));
vi.mock("@excalidraw/excalidraw/index.css", () => ({}));
vi.mock("mermaid", () => ({ default: { initialize() {}, render: async () => ({ svg: "" }), parse: async () => true } }));
vi.mock("vega-embed", () => ({ default: async () => ({ finalize() {} }) }));

import { BlockNoteEditor } from "@blocknote/core";
import { schema } from "./schema";
import { editorToNote, noteToEditor, type BNBlock } from "../convert/note";
import { SAMPLE_NOTE } from "../convert/fixtures";

describe("BlockNote schema", () => {
  it("noteToEditor 的輸出能載入 BlockNote，editorToNote 還原後相同", () => {
    const editor = BlockNoteEditor.create({ schema });
    editor.mount(document.createElement("div"));
    editor.replaceBlocks(editor.document, noteToEditor(SAMPLE_NOTE) as never);
    expect(editorToNote(editor.document as unknown as BNBlock[])).toEqual(SAMPLE_NOTE);
  });
});
```

- [ ] **Step 7: 跑測試**

Run: `npx vitest run src/editor && npx tsc --noEmit`
Expected: `5 passed`、tsc 無錯誤。若 schema 測試失敗，先看差異：(a) BlockNote 給 inline 內容加了額外樣式欄位 → 在 `inlineToMarkdown` 只讀 bold/italic/code（已如此，應不受影響）；(b) column width 數值精度 → 確認 `noteToEditor` 的 width 計算；(c) `editor.mount` 不存在 → 移除該行再試。修正後所有 src 測試要一起重跑：`npx vitest run`。

- [ ] **Step 8: Commit**

```bash
git add frontend && git commit -m "feat(frontend): resizable frame and custom chart/diagram/figure/whiteboard/eli5 blocks"
```

---

### Task 10: 筆記編輯頁（自動存檔、斜線選單、鎖定、高亮）

**Files:**
- Create: `frontend/src/editor/NoteEditor.tsx`
- Create: `frontend/src/pages/PaperView.tsx`
- Modify: `frontend/src/App.tsx`（加入 `#/paper/<slug>` 路由）

**Interfaces:**
- Consumes: `schema`（Task 9）、`noteToEditor` / `editorToNote`（Task 8）、`api`（Task 7）、`slugStore`
- Produces:
  - `interface Selection { blockIds: string[]; selectedText: string; preview: string }`
  - `interface NoteEditorHandle { flush(): Promise<void>; applyReplace(ids: string[], blocks: NoteBlock[]): string[]; loadNote(note: Note): void; setLocked(locked: boolean): void }`
  - `NoteEditor`（forwardRef）props `{ slug, initial: Note, onSelection(sel), onSaveError(msg | null) }`
  - `PaperView` props `{ slug }`；Task 11 會在右側加上 ChatPanel

- [ ] **Step 1: 實作 NoteEditor**

`frontend/src/editor/NoteEditor.tsx`：
```tsx
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";
import { filterSuggestionItems, locales as coreLocales } from "@blocknote/core";
import "@blocknote/core/fonts/inter.css";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/mantine/style.css";
import { SuggestionMenuController, getDefaultReactSlashMenuItems, useCreateBlockNote } from "@blocknote/react";
import { getMultiColumnSlashMenuItems, locales as multiColumnLocales, multiColumnDropCursor } from "@blocknote/xl-multi-column";
import { api } from "../api";
import { editorToNote, noteToEditor, type BNBlock } from "../convert/note";
import type { Note, NoteBlock } from "../types";
import { schema } from "./schema";
import { slugStore } from "./slugStore";

export interface Selection {
  blockIds: string[];
  selectedText: string;
  preview: string;
}

export interface NoteEditorHandle {
  flush(): Promise<void>;
  applyReplace(ids: string[], blocks: NoteBlock[]): string[];
  loadNote(note: Note): void;
  setLocked(locked: boolean): void;
}

interface Props {
  slug: string;
  initial: Note;
  onSelection: (sel: Selection) => void;
  onSaveError: (msg: string | null) => void;
}

function flash(ids: string[]) {
  requestAnimationFrame(() => {
    for (const id of ids) {
      const el = document.querySelector(`[data-id="${id}"]`);
      if (!el) continue;
      el.classList.add("ai-flash");
      window.setTimeout(() => el.classList.remove("ai-flash"), 2000);
    }
  });
}

function blockText(b: { content?: unknown; type: string }) {
  if (!Array.isArray(b.content)) return `［${b.type}］`;
  return b.content.map((c: { text?: string; content?: { text?: string }[] }) => c.text ?? c.content?.map((x) => x.text ?? "").join("") ?? "").join("");
}

export const NoteEditor = forwardRef<NoteEditorHandle, Props>(function NoteEditor({ slug, initial, onSelection, onSaveError }, ref) {
  slugStore.current = slug;
  const editor = useCreateBlockNote({
    schema,
    initialContent: noteToEditor(initial) as never,
    dropCursor: multiColumnDropCursor,
    dictionary: { ...coreLocales.zhTW, multi_column: multiColumnLocales.zh } as never,
  });
  const saveTimer = useRef<number | undefined>(undefined);
  const pending = useRef<Promise<void>>(Promise.resolve());

  const save = useCallback(() => {
    saveTimer.current = undefined;
    const note = editorToNote(editor.document as unknown as BNBlock[]);
    pending.current = api
      .saveNote(slug, note)
      .then(() => onSaveError(null))
      .catch((e: Error) => onSaveError(`存檔失敗：${e.message}（內容仍在畫面上，請勿關閉分頁）`));
    return pending.current;
  }, [editor, slug, onSaveError]);

  const onChange = () => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(save, 1000);
  };

  useEffect(() => () => window.clearTimeout(saveTimer.current), []);

  useImperativeHandle(
    ref,
    () => ({
      async flush() {
        if (saveTimer.current !== undefined) {
          window.clearTimeout(saveTimer.current);
          await save();
        } else {
          await pending.current;
        }
      },
      applyReplace(ids, blocks) {
        const { insertedBlocks } = editor.replaceBlocks(ids, noteToEditor({ blocks }) as never);
        const newIds = insertedBlocks.map((b) => b.id);
        flash(newIds);
        return newIds;
      },
      loadNote(note) {
        editor.replaceBlocks(editor.document, noteToEditor(note) as never);
      },
      setLocked(locked) {
        editor.isEditable = !locked;
      },
    }),
    [editor, save],
  );

  const onSelectionChange = () => {
    const sel = editor.getSelection();
    const blocks = (sel ? sel.blocks : [editor.getTextCursorPosition().block]).filter((b) => b.type !== "column");
    const text = (window.getSelection()?.toString() ?? "").slice(0, 2000);
    onSelection({
      blockIds: blocks.map((b) => b.id),
      selectedText: text,
      preview: text || (blocks[0] ? blockText(blocks[0] as never) : ""),
    });
  };

  return (
    <BlockNoteView editor={editor} onChange={onChange} onSelectionChange={onSelectionChange} slashMenu={false} theme="light">
      <SuggestionMenuController
        triggerCharacter="/"
        getItems={async (query) =>
          filterSuggestionItems(
            [
              ...getDefaultReactSlashMenuItems(editor),
              ...getMultiColumnSlashMenuItems(editor),
              ...paperNotesItems(editor),
            ],
            query,
          )
        }
      />
    </BlockNoteView>
  );
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function paperNotesItems(editor: any) {
  const insert = (type: string) => () => editor.insertBlocks([{ type }], editor.getTextCursorPosition().block, "after");
  const group = "Paper Notes";
  return [
    { title: "白話解釋（ELI5）", aliases: ["eli5", "白話"], group, onItemClick: insert("eli5") },
    { title: "數據圖", aliases: ["chart", "圖表", "長條圖"], group, onItemClick: insert("chart") },
    { title: "概念圖", aliases: ["diagram", "mermaid", "流程圖"], group, onItemClick: insert("diagram") },
    { title: "論文原圖", aliases: ["figure", "原圖", "圖片"], group, onItemClick: insert("figure") },
    { title: "白板", aliases: ["whiteboard", "excalidraw", "手繪"], group, onItemClick: insert("whiteboard") },
  ];
}
```

- [ ] **Step 2: 實作 PaperView 並加路由**

`frontend/src/pages/PaperView.tsx`：
```tsx
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { NoteEditor, type NoteEditorHandle, type Selection } from "../editor/NoteEditor";
import type { Note } from "../types";

export function PaperView({ slug }: { slug: string }) {
  const [note, setNote] = useState<Note | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [, setSelection] = useState<Selection | null>(null);
  const editorRef = useRef<NoteEditorHandle>(null);

  useEffect(() => {
    setNote(null);
    api
      .note(slug)
      .then(setNote)
      .catch((e: ApiError) => setError(e.status === 404 ? "這篇論文還沒有筆記（匯入可能失敗或尚未完成）" : e.message));
  }, [slug]);

  if (error) return <div className="paper-list"><p className="job-error">{error}</p><a href="#/">回列表</a></div>;
  if (!note) return <div className="paper-list">載入中…</div>;

  return (
    <div className="paper-view">
      <main className="note-pane">
        {saveError && <div className="banner-error">{saveError}</div>}
        <NoteEditor ref={editorRef} key={slug} slug={slug} initial={note} onSelection={setSelection} onSaveError={setSaveError} />
      </main>
    </div>
  );
}
```

`frontend/src/App.tsx` 改為：
```tsx
import { useEffect, useState } from "react";
import { HealthLight } from "./HealthLight";
import { PaperList } from "./pages/PaperList";
import { PaperView } from "./pages/PaperView";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const onChange = () => setHash(location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const m = hash.match(/^#\/paper\/([a-z0-9-]+)$/);
  return (
    <>
      <header className="app-header">
        <a href="#/">Paper Notes</a>
        <HealthLight />
      </header>
      {m ? <PaperView slug={m[1]} /> : <PaperList />}
    </>
  );
}
```

- [ ] **Step 3: 型別檢查與既有測試**

Run: `npx tsc --noEmit && npx vitest run`
Expected: tsc 無錯誤；全部測試 passed。

- [ ] **Step 4: 手動煙霧測試（用假 AI）**

```bash
cd ~/projects/paper-notes && mkdir -p .e2e && R=$(pwd)
backend/.venv/bin/python backend/tests/make_sample_pdf.py .e2e/sample.pdf
(cd backend && PAPER_NOTES_DATA=$R/.e2e/data PAPER_NOTES_CLAUDE_BIN=$R/backend/tests/fake_cli.py \
  FAKE_AI_RESPONSES=$R/frontend/e2e/fixtures/ai-responses.json FAKE_AI_STATE=$R/.e2e/state \
  .venv/bin/uvicorn paper_notes.main:app --port 8000 &)
(cd frontend && npx vite --port 5173 &)
```
（`frontend/e2e/fixtures/ai-responses.json` 在 Task 12 Step 1 建立；若尚未建立，先執行 Task 12 Step 1 再回來。）
在瀏覽器開 `http://localhost:5173`，上傳 `.e2e/sample.pdf`，確認：筆記出現、圖表畫得出來、拖右下角把手會改大小、輸入 `/數據圖` 能插入新圖、修改後 1 秒 `.e2e/data/*/note.json` 時間戳更新。結束後 `pkill -f "uvicorn paper_notes"; pkill -f vite`。

- [ ] **Step 5: Commit**

```bash
git add frontend && git commit -m "feat(frontend): note editor page with autosave, slash menu and AI hooks"
```

---

### Task 11: 右側聊天欄

**Files:**
- Create: `frontend/src/chat/ChatPanel.tsx`
- Test: `frontend/src/chat/ChatPanel.test.tsx`
- Modify: `frontend/src/pages/PaperView.tsx`（掛上 ChatPanel）

**Interfaces:**
- Consumes: `NoteEditorHandle`、`Selection`（Task 10）；`api.chat`、`api.edit`、`api.restore`、`ApiError`（Task 7）
- Produces: `ChatPanel` props `{ slug: string; selection: Selection | null; editorRef: React.RefObject<NoteEditorHandle | null> }`

**與 spec 的刻意差異：** spec 寫「被選取區塊鎖定」，BlockNote 沒有單一區塊唯讀的 API，因此改為 AI 修改期間整份筆記暫時唯讀（可捲動閱讀、不可編輯），比 spec 更嚴格、實作單純。

**送出流程（順序很重要）：** `flush()`（先把手動修改存檔，避免快照與 AI 看到舊內容）→ `setLocked(true)` → `api.edit` → 解鎖 → 有 `replace` 才 `applyReplace`（一次 undo 步驟）→ 聊天欄加入回覆。任何錯誤都要解鎖。

- [ ] **Step 1: 寫失敗的測試**

`frontend/src/chat/ChatPanel.test.tsx`：
```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { ChatPanel } from "./ChatPanel";
import { ApiError, api } from "../api";
import type { NoteEditorHandle } from "../editor/NoteEditor";

function fakeEditor() {
  const calls: string[] = [];
  const handle: NoteEditorHandle = {
    flush: vi.fn(async () => { calls.push("flush"); }),
    setLocked: vi.fn((l: boolean) => { calls.push(l ? "lock" : "unlock"); }),
    applyReplace: vi.fn(() => { calls.push("apply"); return ["n1"]; }),
    loadNote: vi.fn(() => { calls.push("load"); }),
  };
  const ref = createRef<NoteEditorHandle>() as { current: NoteEditorHandle | null };
  ref.current = handle;
  return { ref, handle, calls };
}

const selection = { blockIds: ["p1"], selectedText: "這句", preview: "這句" };

beforeEach(() => {
  vi.spyOn(api, "chat").mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function send(text: string) {
  fireEvent.change(screen.getByPlaceholderText(/例如/), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /送出/ }));
}

describe("ChatPanel", () => {
  it("修改：flush → lock → edit → unlock → apply，並顯示回覆與還原按鈕", async () => {
    const { ref, handle, calls } = fakeEditor();
    const edit = vi.spyOn(api, "edit").mockResolvedValue({
      reply: "已改寫", replace: [{ id: "x", type: "paragraph", text: "新" }], snapshot: "20261001-120000-abcd.json",
    });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("改白話");
    await screen.findByText("已改寫");
    expect(edit).toHaveBeenCalledWith("s", { engine: "claude", message: "改白話", block_ids: ["p1"], selected_text: "這句" });
    expect(calls).toEqual(["flush", "lock", "unlock", "apply"]);
    expect(handle.applyReplace).toHaveBeenCalledWith(["p1"], [{ id: "x", type: "paragraph", text: "新" }]);
    expect(screen.getByRole("button", { name: "還原到此修改前" })).toBeTruthy();
  });

  it("只討論：不套用修改", async () => {
    const { ref, handle } = fakeEditor();
    vi.spyOn(api, "edit").mockResolvedValue({ reply: "這是在說…", replace: null, snapshot: null });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("什麼意思？");
    await screen.findByText("這是在說…");
    expect(handle.applyReplace).not.toHaveBeenCalled();
  });

  it("錯誤：顯示錯誤與原始輸出，並解鎖", async () => {
    const { ref, calls } = fakeEditor();
    vi.spyOn(api, "edit").mockRejectedValue(new ApiError("AI 回傳格式錯誤", 502, "[{]"));
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    await send("改");
    await screen.findByText("AI 回傳格式錯誤");
    expect(screen.getByText("[{]")).toBeTruthy();
    expect(calls).toEqual(["flush", "lock", "unlock"]);
  });

  it("切換引擎為 Codex", async () => {
    const { ref } = fakeEditor();
    const edit = vi.spyOn(api, "edit").mockResolvedValue({ reply: "ok", replace: null, snapshot: null });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    fireEvent.change(screen.getByLabelText("AI 引擎"), { target: { value: "codex" } });
    await send("hi");
    await waitFor(() => expect(edit.mock.calls[0][1].engine).toBe("codex"));
  });

  it("沒有選取時不能送出", () => {
    const { ref } = fakeEditor();
    render(<ChatPanel slug="s" selection={null} editorRef={ref} />);
    fireEvent.change(screen.getByPlaceholderText(/例如/), { target: { value: "x" } });
    expect((screen.getByRole("button", { name: /送出/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("還原：flush → restore → loadNote", async () => {
    const { ref, handle } = fakeEditor();
    vi.spyOn(api, "chat").mockResolvedValue([
      { role: "assistant", text: "已改寫", snapshot: "20261001-120000-abcd.json", ts: 1 },
    ]);
    const restore = vi.spyOn(api, "restore").mockResolvedValue({ blocks: [] });
    render(<ChatPanel slug="s" selection={selection} editorRef={ref} />);
    fireEvent.click(await screen.findByRole("button", { name: "還原到此修改前" }));
    await waitFor(() => expect(handle.loadNote).toHaveBeenCalledWith({ blocks: [] }));
    expect(restore).toHaveBeenCalledWith("s", "20261001-120000-abcd.json");
    expect(handle.flush).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `npx vitest run src/chat`
Expected: FAIL（`Failed to resolve import "./ChatPanel"`）

- [ ] **Step 3: 實作 ChatPanel**

`frontend/src/chat/ChatPanel.tsx`：
```tsx
import { useEffect, useState, type RefObject } from "react";
import { ApiError, api } from "../api";
import type { NoteEditorHandle, Selection } from "../editor/NoteEditor";
import type { ChatEntry, Engine } from "../types";

interface Props {
  slug: string;
  selection: Selection | null;
  editorRef: RefObject<NoteEditorHandle | null>;
}

export function ChatPanel({ slug, selection, editorRef }: Props) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [engine, setEngine] = useState<Engine>("claude");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.chat(slug).then(setEntries).catch(() => setEntries([]));
  }, [slug]);

  const push = (e: Omit<ChatEntry, "ts">) => setEntries((prev) => [...prev, { ...e, ts: Date.now() / 1000 }]);

  const send = async () => {
    const editor = editorRef.current;
    const text = message.trim();
    if (!editor || !selection || !text || busy) return;
    const sel = selection;
    setBusy(true);
    setMessage("");
    push({ role: "user", text, engine });
    let locked = false;
    try {
      await editor.flush();
      editor.setLocked(true);
      locked = true;
      const res = await api.edit(slug, { engine, message: text, block_ids: sel.blockIds, selected_text: sel.selectedText });
      editor.setLocked(false);
      locked = false;
      if (res.replace) editor.applyReplace(sel.blockIds, res.replace);
      push({ role: "assistant", text: res.reply, engine, snapshot: res.snapshot });
    } catch (e) {
      push({ role: "error", text: (e as Error).message, raw: e instanceof ApiError ? e.raw : null });
    } finally {
      if (locked) editor.setLocked(false);
      setBusy(false);
    }
  };

  const restore = async (snapshot: string) => {
    const editor = editorRef.current;
    if (!editor || busy) return;
    try {
      await editor.flush();
      editor.loadNote(await api.restore(slug, snapshot));
      push({ role: "assistant", text: "已還原到這次修改之前的版本" });
    } catch (e) {
      push({ role: "error", text: `還原失敗：${(e as Error).message}` });
    }
  };

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span>與 AI 討論</span>
        <select aria-label="AI 引擎" value={engine} onChange={(e) => setEngine(e.target.value as Engine)} disabled={busy}>
          <option value="claude">Claude</option>
          <option value="codex">Codex</option>
        </select>
      </div>
      <div className="chat-log">
        {entries.map((e, i) => (
          <div key={i} className={`chat-msg chat-${e.role}`}>
            <div>{e.text}</div>
            {e.role === "assistant" && e.snapshot && (
              <button className="chat-restore" onClick={() => restore(e.snapshot!)}>還原到此修改前</button>
            )}
            {e.role === "error" && e.raw && (
              <details>
                <summary>AI 原始輸出</summary>
                <pre>{e.raw}</pre>
              </details>
            )}
          </div>
        ))}
        {busy && <div className="chat-msg chat-pending">AI 處理中…（可能需要 30 秒到幾分鐘，期間筆記暫時鎖定）</div>}
      </div>
      <div className="chat-selection">
        {selection ? <>已選取：「{selection.preview.slice(0, 80)}」</> : "先在左側筆記點選或反白要討論的內容"}
      </div>
      <div className="chat-input">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="例如：把這段改得更白話、幫我加一張比較圖、這裡的實驗設定是什麼意思？"
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
          }}
        />
        <button onClick={send} disabled={busy || !selection || !message.trim()}>送出（⌘/Ctrl + Enter）</button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `npx vitest run src/chat`
Expected: `6 passed`

- [ ] **Step 5: 掛上 PaperView**

`frontend/src/pages/PaperView.tsx`：
- import 加：`import { ChatPanel } from "../chat/ChatPanel";`
- 把 `const [, setSelection] = useState<Selection | null>(null);` 改為 `const [selection, setSelection] = useState<Selection | null>(null);`
- 在 `</main>` 後面加：`<ChatPanel slug={slug} selection={selection} editorRef={editorRef} />`

Run: `npx tsc --noEmit && npx vitest run`
Expected: tsc 無錯誤；全部測試 passed。

- [ ] **Step 6: Commit**

```bash
git add frontend && git commit -m "feat(frontend): chat panel with select-discuss-replace and restore"
```

---

### Task 12: 端對端測試、啟動腳本、真實論文驗收

**Files:**
- Create: `frontend/e2e/fixtures/ai-responses.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/app.spec.ts`
- Create: `dev.sh`
- Create: `README.md`

**Interfaces:**
- Consumes: 全部前述 Task。E2E 用 `backend/tests/fake_cli.py` 取代真 AI，回應依序為：摘要 → 筆記 → 一次修改。

- [ ] **Step 1: 假 AI 回應檔**

`frontend/e2e/fixtures/ai-responses.json`：
```json
[
  {"summary_md": "# 摘要\n這是一篇測試論文。研究問題是如何驗證筆記系統，方法是用假的 AI 回應，結果在 Table 1, p.1。"},
  {"reply": "已產生筆記", "blocks_json": "[{\"type\":\"heading\",\"level\":1,\"text\":\"E2E 測試論文\"},{\"type\":\"heading\",\"level\":2,\"text\":\"方法\"},{\"type\":\"paragraph\",\"text\":\"原始段落文字\"},{\"type\":\"eli5\",\"text\":\"就像用假人練習急救。\"},{\"type\":\"chart\",\"spec\":{\"mark\":\"bar\",\"data\":{\"values\":[{\"x\":\"A\",\"y\":1},{\"x\":\"B\",\"y\":3}]},\"encoding\":{\"x\":{\"field\":\"x\",\"type\":\"nominal\"},\"y\":{\"field\":\"y\",\"type\":\"quantitative\"}}},\"source\":\"Table 1, p.1\"},{\"type\":\"figure\",\"path\":\"page-1.png\",\"caption\":\"第一頁\",\"page\":1}]"},
  {"reply": "已改寫成白話", "blocks_json": "[{\"type\":\"paragraph\",\"text\":\"改寫後的段落\"}]"}
]
```

- [ ] **Step 2: Playwright 設定（自動啟動假 AI 後端與 Vite）**

`frontend/playwright.config.ts`：
```ts
import { defineConfig } from "@playwright/test";

const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const E2E = `${ROOT}/.e2e`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: [
        `rm -rf ${E2E} && mkdir -p ${E2E}/data`,
        `${ROOT}/backend/.venv/bin/python ${ROOT}/backend/tests/make_sample_pdf.py ${E2E}/sample.pdf`,
        `cd ${ROOT}/backend && PAPER_NOTES_DATA=${E2E}/data PAPER_NOTES_CLAUDE_BIN=${ROOT}/backend/tests/fake_cli.py ` +
          `PAPER_NOTES_CODEX_BIN=${ROOT}/backend/tests/fake_cli.py FAKE_AI_RESPONSES=${ROOT}/frontend/e2e/fixtures/ai-responses.json ` +
          `FAKE_AI_STATE=${E2E}/state .venv/bin/uvicorn paper_notes.main:app --port 8765`,
      ].join(" && "),
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: false,
    },
    {
      command: "VITE_API_TARGET=http://127.0.0.1:8765 npx vite --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
    },
  ],
});
```

- [ ] **Step 3: 寫 E2E 測試**

`frontend/e2e/app.spec.ts`：
```ts
import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLE = path.resolve(new URL("../..", import.meta.url).pathname, ".e2e/sample.pdf");

test("匯入 → 選取討論 → AI 改寫 → 復原 → 拖曳圖表 → 重新整理後版面保留", async ({ page }) => {
  const note = page.locator(".note-pane");
  await page.goto("/");
  await page.getByLabel("論文 PDF").setInputFiles(SAMPLE);
  await page.getByLabel("標題").fill("E2E 測試論文");
  await page.getByRole("button", { name: "開始整理" }).click();

  await expect(page).toHaveURL(/#\/paper\//, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "E2E 測試論文" })).toBeVisible();
  await expect(note.getByText("就像用假人練習急救。")).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 抽取，待核對" })).toBeVisible();
  await expect(page.locator("img.figure-img")).toBeVisible();

  // 選取段落 → 送出 → 被取代
  await note.getByText("原始段落文字").click();
  await expect(page.locator(".chat-selection")).toContainText("原始段落文字");
  await page.getByPlaceholder(/例如/).fill("改白話");
  await page.getByRole("button", { name: /送出/ }).click();
  await expect(note.getByText("改寫後的段落")).toBeVisible({ timeout: 20_000 });
  await expect(note.getByText("原始段落文字")).toHaveCount(0);
  await expect(page.getByText("已改寫成白話")).toBeVisible();

  // 一次 undo 撤回整個 AI 修改
  await note.getByText("改寫後的段落").click();
  await page.keyboard.press("ControlOrMeta+z");
  await expect(note.getByText("原始段落文字")).toBeVisible();
  await expect(note.getByText("改寫後的段落")).toHaveCount(0);

  // 拖曳圖表右下角把寬度縮小
  const frame = page.locator(".frame").filter({ has: page.locator(".chart-canvas") }).first();
  await frame.hover();
  const before = (await frame.boundingBox())!;
  const handle = (await frame.locator(".frame-resize").boundingBox())!;
  await page.mouse.move(handle.x + 5, handle.y + 5);
  await page.mouse.down();
  await page.mouse.move(handle.x - 200, handle.y + 5, { steps: 10 });
  await page.mouse.up();
  const after = (await frame.boundingBox())!;
  expect(after.width).toBeLessThan(before.width - 150);

  // 等自動存檔後重新整理，寬度保留
  await page.waitForTimeout(1500);
  await page.reload();
  const reloaded = page.locator(".frame").filter({ has: page.locator(".chart-canvas") }).first();
  await expect(reloaded).toBeVisible();
  expect(Math.abs((await reloaded.boundingBox())!.width - after.width)).toBeLessThan(4);
  await expect(note.getByText("原始段落文字")).toBeVisible();
});
```

- [ ] **Step 4: 跑 E2E**

Run：
```bash
cd ~/projects/paper-notes/frontend && npx playwright install chromium && npx playwright test
```
Expected: `1 passed`。失敗時看 `npx playwright show-report`；常見原因：(a) BlockNote 區塊外層沒有 `data-id` → `flash` 失效但不影響測試；(b) undo 需要編輯器有焦點 → 測試已先 click；(c) 圖表選擇器找不到 → 確認 `.frame` 內有 `.chart-canvas`。

- [ ] **Step 5: 啟動腳本與 README**

`dev.sh`：
```bash
#!/usr/bin/env bash
# 一鍵啟動 Paper Notes：後端 http://127.0.0.1:8000、前端 http://localhost:5173
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
trap 'kill 0' EXIT
(cd "$ROOT/backend" && .venv/bin/uvicorn paper_notes.main:app --port 8000) &
(cd "$ROOT/frontend" && npx vite --port 5173) &
sleep 2 && open "http://localhost:5173" || true
wait
```
Run: `chmod +x dev.sh`

`README.md`：
````markdown
# Paper Notes

把論文 PDF 整理成報 paper 用的筆記：AI 產生白話解釋與圖表，選取任一區塊在右側與 AI 討論並直接改寫。

## 第一次安裝
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && cd ..
cd frontend && npm install && cd ..
```
需要本機已登入 `claude`（Claude Code）與／或 `codex`（Codex CLI）。

## 啟動
```bash
./dev.sh
```

## 使用
- 首頁上傳 PDF，選 Claude 或 Codex，等 1–3 分鐘。
- 點選或反白筆記內容 → 右側輸入指令 → AI 直接改寫；不滿意按 Ctrl/⌘+Z，或點「還原到此修改前」。
- 圖表：拖右下角改大小、拖下緣改間距、工具列切換對齊；把區塊拖到另一區塊左右兩側可並排。
- 黃色「AI 抽取，待核對」：對過論文原文後點一下確認。
- 輸入 `/` 插入：白話解釋、數據圖、概念圖、論文原圖、白板、多欄。

## 測試
```bash
cd backend && .venv/bin/pytest -q
cd frontend && npx vitest run && npx playwright test
```

## 資料位置
`papers/<論文>/`：`paper.pdf`、`figures/`、`summary.md`、`note.json`、`history/`（AI 修改前快照）、`chat.jsonl`。
````

- [ ] **Step 6: 全套測試**

Run：
```bash
cd ~/projects/paper-notes/backend && .venv/bin/pytest -q
cd ../frontend && npx tsc --noEmit && npx vitest run && npx playwright test
```
Expected：後端全數 passed；tsc 無錯誤；Vitest 全數 passed；Playwright `1 passed`。

- [ ] **Step 7: Commit**

```bash
cd ~/projects/paper-notes && git add -A && git commit -m "test: end-to-end flow with fake AI; add dev script and README"
```

- [ ] **Step 8: 真實論文驗收（使用者一起看，對照 spec 第 1 節成功標準）**

使用者提供一篇真實論文 PDF，執行 `./dev.sh`，逐項確認並記錄結果：

1. [ ] 用 Claude 匯入，5 分鐘內出現筆記：有六個段落 heading、每段有白話框、至少一張圖（數據圖／概念圖／原圖）。記下實際耗時。
2. [ ] 抽查 1 張數據圖：數字與論文原表格一致（不一致就記下，這是 prompt 要改的訊號）。
3. [ ] 選一段文字請 AI「改得更白話」→ 被取代並高亮 → ⌘/Ctrl+Z 一次就完整撤回。
4. [ ] 問一個純問題（「這個指標是什麼意思？」）→ 只回答、筆記不變。
5. [ ] 拖曳一張圖改寬高、拉下緣改間距、把兩個區塊拖成並排 → 重新整理後全部保留。
6. [ ] 聊天欄切到 Codex 做一次修改 → 成功。
7. [ ] 點「還原到此修改前」→ 筆記回到該次修改前。

任何一項不過：記錄現象，回到對應 Task 修正後重跑 Step 6。
