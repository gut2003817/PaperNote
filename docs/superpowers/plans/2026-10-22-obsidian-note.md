# 一鍵寫進 Obsidian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 閱讀頁按一顆鈕，AI 讀論文與讀者劃線，在使用者的 Obsidian vault 新增一篇結構固定、含 30 秒口語開場、原圖與 Mermaid 的筆記，且永不覆蓋既有檔案。

**Architecture:** 新增純函式模組負責 vault 路徑驗證、檔名、組檔；AI 只回結構化 JSON（敘述段落、標籤、簡稱、挑哪些圖、Mermaid），程式負責 frontmatter、劃線與頁碼、圖片截取與命名、寫檔。以 `jobs` 的小任務（kind `"obsidian"`）背景執行，前端輪詢 `/api/jobs?pid=`。

**Tech Stack:** Python 標準庫伺服器、`pypdfium2`＋PIL（已有）、vanilla JS；不新增依賴。

**Spec:** `docs/superpowers/specs/2026-10-22-obsidian-note-design.md`

## Global Constraints

- 只有使用者按按鈕才呼叫 AI；不在匯入後自動跑（spec §3）。
- Vault 預設值 `/Users/ting/Documents/Obsidian Vault` 不寫死在程式；用設定鍵 `obsidian_vault`，預設空字串（spec §3、§6）。
- 筆記寫在 `<vault>/論文筆記/`，圖片寫在 `<vault>/論文筆記/附圖/`；只新建這兩個資料夾，不碰 `.obsidian`、既有筆記（spec §2、§3）。
- 永不覆蓋既有檔案；重按另存新檔、檔名加時間（spec §4）。
- 圖檔名「論文簡稱＋圖號＋一句描述」，例如 `6G-SAGIN-圖2-整體架構.png`，不用雜湊（spec §4）。
- 結構順序：frontmatter（標籤、年份、作者、來源）→ 單一標題 → 30 秒版（口語、約 150 字內）→ 問題與動機 → 方法重點 → 結果 → 我的劃線（附頁碼）→ 限制與我的想法；「我的想法」留空，AI 不寫感想（spec §4）。
- 內容只來自論文原文；推論須標明是推論（spec §2）。遵循 `langs.NOTE_STYLE` 的寫作規範。
- 不新增第三方依賴；測試用暫存目錄，絕不寫真實 vault、不呼叫真實 AI（spec §3、§7）。
- 程式內中文字串依專案慣例用簡體鍵、經 `tr()`／`PR.t()`，繁體由 `web/i18n/zh-TW.json` 提供；`scripts/i18n_check.py` 須通過。
- 測試指令：`.venv/bin/python -m pytest tests -q`（基準 436 passed, 1 skipped）。不使用 `pkill -f`；不在使用者的 8765 埠做實驗，測試用 port 0。

## Review Focus

1. vault 路徑含空格、是 symlink、不存在、是檔案、不可寫：回明確錯誤、不建任何東西（Task 1）。
2. 論文沒有 figure 區塊、或沒有任何劃線：筆記仍產出，對應段落寫「（本篇無）」之類的明確佔位，不出現空標題或壞連結（Task 4、5）。
3. AI 回的不是合法 JSON（被 ``` 包住、前後有廢話、缺欄位、`figures` 指到不存在的 block id、Mermaid 內含 ```）：容錯或明確失敗，不寫出半成品檔（Task 5）。
4. 簡稱／標題含 `/ : ? * " < > |`、很長、全中文、空字串：檔名合法且可讀（Task 1）。
5. 同一秒內按兩次、`附圖/` 已有同名檔（內容相同／不同）：不覆蓋、不報錯（Task 1、3、6）。

---

### Task 1: Vault 路徑、檔名與不覆蓋寫入

**Files:**
- Create: `easyread/obsidian_vault.py`
- Test: `tests/test_obsidian_vault.py`

**Interfaces:**
- Produces:
  - `check_vault(path: str) -> Path`：回傳 `resolve()` 後的 vault 根。必須是絕對路徑、無 `..` 片段、存在、是目錄、本身不是 symlink、可寫（實際建暫存檔測試後刪除）；不合格拋 `ValueError(tr(...))`。
  - `note_dirs(vault: Path) -> tuple[Path, Path]`：建立並回傳 `(論文筆記, 論文筆記/附圖)`；若這兩個已存在但是 symlink 或檔案則拋 `ValueError`。
  - `safe_name(s: str, limit: int = 40) -> str`：移除 `/\:*?"<>|` 與控制字元、空白轉 `-`、截斷到 `limit` 字、空字串回 `"paper"`。
  - `write_new(dir_: Path, stem: str, suffix: str, data: bytes) -> Path`：用 `open(path, "xb")` 寫入；檔名已存在則在 stem 後依序加 `-2`、`-3`…；不覆蓋，回傳實際路徑。
  - `stamp(now: datetime | None = None) -> str`：`YYYYMMDD-HHMMSS`。

- [ ] **Step 1: Write failing tests** `test_check_vault_rejects_relative_missing_file_symlink_and_dotdot`、`test_check_vault_accepts_path_with_space`（`tmp/"Obsidian Vault"`）、`test_note_dirs_creates_only_two_folders`（建立後 vault 根只多 `論文筆記`；`.obsidian` 內容不變）、`test_safe_name_cases`（斜線、冒號、50 字長名、空字串、全中文原樣保留）、`test_write_new_never_overwrites`（連寫兩次同名，得 `a.md`、`a-2.md`，第一個內容不變）。
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_obsidian_vault.py -q`，預期 FAIL（模組不存在）。
- [ ] **Step 3:** 實作上列四個函式與 `stamp`；`write_new` 用 `FileExistsError` 迴圈而非先檢查再寫，避免競態。
- [ ] **Step 4:** 同指令，預期全 PASS。
- [ ] **Step 5:** `git add easyread/obsidian_vault.py tests/test_obsidian_vault.py && git commit -m "feat: Obsidian vault 路徑驗證與不覆蓋寫入"`

### Task 2: 設定鍵 `obsidian_vault` 與設定頁欄位

**Files:**
- Modify: `easyread/config.py`（`DEFAULTS` 加 `"obsidian_vault": ""`）、`easyread/settings_api.py:8-17`（`save_config` 內驗證）、`easyread/web/js/common/settings.js`（`collect` 帶出新欄位）、閱讀設定分頁的 HTML（沿用 `settings-library.js` 的資料夾選擇方式，重用 `POST /api/library/pick-folder`）
- Test: `tests/test_obsidian_settings.py`

**Interfaces:**
- Consumes: `obsidian_vault.check_vault`
- Produces: 設定鍵 `obsidian_vault: str`；空字串表示未設定；`save_config` 對非空值呼叫 `check_vault`，不合格拋 `ValueError`（伺服器回 400），**整個 patch 不寫盤**。

- [ ] **Step 1:** 測試 `test_save_config_accepts_valid_vault`、`test_save_config_rejects_bad_vault_and_writes_nothing`（不合格時 `config.json` 未改變）、`test_empty_vault_allowed`。用暫存 `EASYREAD_HOME`。
- [ ] **Step 2:** 跑測試，預期 FAIL。
- [ ] **Step 3:** 在 `save_config` 的 `target` 驗證旁加 vault 驗證；前端加「Obsidian 資料夾」欄位（文字框＋「選擇資料夾」按鈕），未設定時按鈕提示去設定。
- [ ] **Step 4:** 跑測試 PASS；`node tests/test_*.cjs` 中與設定相關者不得壞；`.venv/bin/python scripts/i18n_check.py` 通過。
- [ ] **Step 5:** commit `feat: 設定頁加 Obsidian 資料夾`。

### Task 3: 把論文圖截成 PNG 放進附圖

**Files:**
- Modify: `easyread/pdfwork.py`（在 `crop` 旁新增函式）
- Create: `easyread/obsidian_figures.py`
- Test: `tests/test_obsidian_figures.py`

**Interfaces:**
- Consumes: `pdfwork.open_pdf`、`pdfwork.crop` 的 `box`（頁面歸一化 `[x0,y0,x1,y1]`）慣例、`obsidian_vault.safe_name`、`write_new`。
- Produces:
  - `pdfwork.crop_png(root: Path, page: int, box: list[float], scale: float = 3.0) -> bytes`：回傳 PNG 位元組，不寫檔。
  - `obsidian_figures.export_figure(ws, block: dict, short: str, desc: str, attach_dir: Path) -> str`：截圖並以「`{safe_name(short)}-圖{num}-{safe_name(desc)}.png`」寫入 `attach_dir`；同名且內容相同就重用該檔（比對 sha256），內容不同就加後綴；回傳**實際檔名**。`block` 沒有 `box` 時拋 `ValueError`。

- [ ] **Step 1:** 測試 `test_crop_png_returns_png_bytes`、`test_export_figure_names_file_readably`（檔名含簡稱、`圖2`、描述）、`test_export_figure_same_content_is_reused`、`test_export_figure_different_content_gets_suffix_not_overwritten`、`test_export_figure_without_box_raises`。測試 PDF 用 repo 既有 fixture；若無，以 PIL 存一頁 PDF 於暫存目錄。
- [ ] **Step 2:** 跑測試，預期 FAIL。
- [ ] **Step 3:** 實作；`crop_png` 重用 `crop` 內部的渲染與裁切（抽共用小函式，不複製貼上）。
- [ ] **Step 4:** 跑測試 PASS；既有 `tests/` 與圖相關測試不得壞（全量 pytest）。
- [ ] **Step 5:** commit `feat: 論文圖截成 PNG 供 Obsidian 使用`。

### Task 4: 蒐集筆記素材（meta、劃線＋頁碼、可選圖清單）

**Files:**
- Create: `easyread/obsidian_context.py`
- Test: `tests/test_obsidian_context.py`

**Interfaces:**
- Consumes: `ws.load("paper")`、`ws.load("reader")`、`ws.load("item")`；meta 合併規則同 `library.py:42-55`（`meta_override` 優先）。
- Produces:
  - `collect(ws) -> dict`：`{"title": str, "authors": list[str], "year": str, "source": str, "marks": list[{"quote": str, "page": int|None, "side": str, "body": str}], "figures": list[{"id": str, "num": str|int, "page": int, "caption": str, "type": "figure"|"table", "has_box": bool}], "text": str}`。
  - 劃線頁碼由 `note["anchor"]` 對應 `paper["blocks"]` 的 `page`；找不到為 `None`。只收未 `deleted` 且有 `quote` 的 note，依 block 順序排。`source` 依序取 doi→arxiv→url→空。`text` 為給非 claude 引擎的譯文節選（上限 14000 字，參考 `notehelp.prompt`）。

- [ ] **Step 1:** 測試 `test_collect_marks_have_pages_and_skip_deleted`、`test_collect_without_highlights_returns_empty_marks`、`test_collect_without_figures`、`test_collect_meta_override_wins`、`test_collect_missing_year_authors_gives_empty_values`（不拋例外）。用手寫的最小 `paper.json`／`reader.json` 於暫存目錄。
- [ ] **Step 2:** 跑測試，預期 FAIL。
- [ ] **Step 3:** 實作；不呼叫 `chat._marks`（內部函式、輸出是給提示詞的文字，不合用）。
- [ ] **Step 4:** 跑測試 PASS。
- [ ] **Step 5:** commit `feat: Obsidian 筆記素材蒐集`。

### Task 5: 提示詞、AI 回覆解析與 Markdown 組裝

**Files:**
- Create: `easyread/obsidian_note.py`
- Test: `tests/test_obsidian_note.py`

**Interfaces:**
- Consumes: Task 4 的 `collect()` 輸出；`langs.note_style`／`NOTE_STYLE`。
- Produces:
  - `build_prompt(ctx: dict, engine: str) -> str`：要求只回一個 JSON 物件，欄位 `hook`（口語 30 秒開場，約 150 字內，含一句話亮點與 2~3 個為什麼值得聽）、`short`（論文簡稱，英數與連字號）、`tags`（3~5 個）、`problem`、`method`、`result`、`limits`（皆 Markdown 字串，內容只能來自論文，推論須標明）、`figures`（`[{id, desc}]`，只能從 ctx 的圖清單挑重要的，不限張數）、`diagrams`（`[{title, mermaid}]`，只放 Mermaid 語法本身，不含圍欄）。提示詞明寫：不要寫「我的想法」、不要編造數據。
  - `parse_reply(text: str) -> dict`：容忍 ``` 圍欄與前後廢話，取第一個平衡的 JSON 物件；缺欄位補預設（字串空、列表空）；`tags` 去 `#` 與空白；`diagrams[].mermaid` 若含 ``` 則去除；解析失敗拋 `ValueError(tr("模型回覆不是有效的 JSON"))`。
  - `render(ctx: dict, data: dict, fig_files: dict[str, str]) -> str`：輸出整篇 Markdown。`fig_files` 為 block id→附圖檔名；圖寫成標準 Markdown 相對連結 `![圖{num} {desc}](附圖/<檔名>)`（相對於 `論文筆記/`），不用 wikilink；每張圖下一行寫 `圖說（第 N 頁）`。Mermaid 用 ```` ```mermaid ```` 圍欄。劃線區每條為 `> quote`＋`（p.N）`，無頁碼省略括號；`marks` 為空時該段寫 `（本篇沒有劃線）`。最後固定輸出 `## 限制與我的想法` 下先放 `limits`，再放 `### 我的想法` 與一行空白（不放任何 AI 文字）。

- [ ] **Step 1:** 測試 `test_render_has_single_h1_and_frontmatter_fields`（開頭 `---`、含 `tags:`、`year:`、`authors:`、`source:`；全文只有一個 `# ` 標題）、`test_render_section_order`（依 Global Constraints 的順序）、`test_render_my_thoughts_is_empty`、`test_render_empty_marks_and_figures_placeholders`、`test_parse_reply_accepts_fenced_json_and_chatter`、`test_parse_reply_missing_fields_defaults`、`test_parse_reply_invalid_raises`、`test_parse_reply_strips_fences_inside_mermaid`、`test_build_prompt_contains_note_style_and_json_only_instruction`（zh-TW）、`test_render_unknown_figure_id_is_dropped`。
- [ ] **Step 2:** 跑測試，預期 FAIL。
- [ ] **Step 3:** 實作三個函式；frontmatter 的 YAML 值用雙引號並跳脫 `"` 與換行，作者用 YAML list。
- [ ] **Step 4:** 跑測試 PASS。
- [ ] **Step 5:** commit `feat: Obsidian 筆記提示詞、解析與組裝`。

### Task 6: 產生流程、背景工作與 API 端點

**Files:**
- Modify: `easyread/obsidian_note.py`（加 `generate`）、`easyread/jobs.py:201-218`（`_small_loop` 加 `elif job["kind"] == "obsidian"`，結果寫 `job["path"]`、`job["figures"]`）、`easyread/server.py:~473-480`（`POST /api/p/<id>/obsidian-note`，在 `annotated-pdf` 旁）
- Test: `tests/test_obsidian_generate.py`

**Interfaces:**
- Consumes: Task 1–5。引擎呼叫 `engines.run(cfg, prompt, cwd, ...)` 的 cfg 以 `chat_models.engine_cfg(config.load(), model_id)` 取得（同 `notehelp.handle`）。
- Produces:
  - `generate(ws, cfg: dict, cancel=None) -> dict`：`{"path": str, "figures": int, "diagrams": int}`。順序：`check_vault(cfg["obsidian_vault"])`（空字串拋 `ValueError(tr("尚未設定 Obsidian 資料夾"))`）→ `collect` → 呼叫引擎 → `parse_reply` → 逐張 `export_figure`（單張失敗只略過並計入 `skipped`，不中止）→ `render` → 寫檔：stem 為 `safe_name(short or title)`；若 `<stem>.md` 已存在，改用 `<stem>-<stamp()>`（spec：重按另存新檔、檔名加時間），再交給 `write_new`（撞名時的 `-2` 只是最後防線）。**AI 呼叫成功之前不建任何資料夾、不寫任何檔**（先驗路徑可、後建資料夾與寫檔）。
  - 端點回傳 `app.jobs.submit_small("obsidian", ws.id)` 的 job；vault 未設定時端點直接回 400，不入佇列。

- [ ] **Step 1:** 測試（以 `unittest.mock.patch("easyread.engines.run")` 回罐頭 JSON）：`test_generate_writes_note_and_figures_into_vault`、`test_generate_twice_creates_second_file_and_keeps_first`、`test_generate_bad_json_writes_nothing`（vault 內無新資料夾）、`test_generate_unset_vault_raises`、`test_generate_skips_figure_without_box_but_succeeds`、`test_endpoint_requires_token_and_400_when_unset`、`test_endpoint_runs_job_to_done`（輪詢 `/api/jobs?pid=` 至 `done` 並含 `path`）。**不呼叫真實引擎，不碰真實 vault。**
- [ ] **Step 2:** 跑測試，預期 FAIL。
- [ ] **Step 3:** 實作 `generate`、`_small_loop` 分支與端點。
- [ ] **Step 4:** 跑本檔測試 PASS，再跑全量 pytest。
- [ ] **Step 5:** commit `feat: 一鍵產生 Obsidian 筆記（背景工作與端點）`。

### Task 7: 前端按鈕、狀態與文件

**Files:**
- Modify: `easyread/web/js/reader/export.js`（匯出對話框加「寫進 Obsidian」，函式 `PR.exportToObsidian`，輪詢 `/api/jobs?pid=`）、`easyread/web/i18n/en.json`、`easyread/web/i18n/zh-TW.json`（依 `scripts/gen_zhtw.py`／`zhtw_overrides.json` 慣例）、`README.md`、`README.zh-TW.md`、`CHANGELOG.md`
- Test: `tests/test_obsidian_ui.cjs`（仿 `tests/test_note_images.cjs`）、`scripts/i18n_check.py`

**Interfaces:**
- Consumes: `POST /api/p/<id>/obsidian-note`（header `X-Token: PR.token`）、`GET /api/jobs?pid=` 的 `state`／`message`／`path`。
- Produces: 使用者可見行為：未設定 vault → toast 引導到設定；執行中顯示「模型思考中」；完成 toast 顯示檔案路徑與「已略過 N 張圖」（若有）；失敗顯示錯誤訊息。按下時 `PR.flush()` 先寫入待存劃線（同 `exportAnnotatedPdf`）。

- [ ] **Step 1:** 寫 `.cjs` 測試：未設定時不發請求且提示、完成時顯示路徑（用假 `fetch`）。
- [ ] **Step 2:** `node tests/test_obsidian_ui.cjs`，預期 FAIL。
- [ ] **Step 3:** 實作前端與 i18n 詞條；README 註明「會消耗訂閱額度、只在你按下時執行、不覆蓋既有檔案、C 之後再做」。
- [ ] **Step 4:** `node tests/test_obsidian_ui.cjs`、`.venv/bin/python scripts/i18n_check.py`、全量 pytest 皆通過。
- [ ] **Step 5:** commit `feat: 閱讀頁「寫進 Obsidian」按鈕與文件`。

### Task 8: 收尾驗證（不由測試取代）

- [ ] 全量：`.venv/bin/python -m pytest tests -q`、各 `node tests/test_*.cjs`、`scripts/i18n_check.py`；貼出輸出。
- [ ] 以暫存 `EASYREAD_HOME`／`EASYREAD_LIBRARY` 與暫存 vault 起一個非 8765 的伺服器，用假引擎（patch 掉 `engines.run`）從 API 走完一次，檢查產出檔的 frontmatter、單一標題、附圖檔名與連結、重按後新檔。不碰真實資料與真實 vault。
- [ ] 請使用者在自己的服務設定 vault（`/Users/ting/Documents/Obsidian Vault`），對一篇有劃線的論文按一次，在 Obsidian 開啟檢查：30 秒版是否口語、圖是否選得合理、Mermaid 是否能顯示、有無編造內容。**此項為使用者驗收，無法由自動測試證明。**
- [ ] 不推上 `PaperNote`，推送前先問使用者。
