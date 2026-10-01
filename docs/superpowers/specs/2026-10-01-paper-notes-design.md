# Paper Notes — 設計規格（第一期：筆記文件）

日期：2026-10-01
狀態：待使用者審閱

## 1. 目的與範圍

**目的**：使用者（研究生，課堂 paper presentation）丟入論文 PDF，由 AI 整理成「報 paper 用」的筆記文件，含白話解釋（ELI5）與圖表；使用者可選取任一部分，在右側聊天欄與 AI 討論，AI 直接改寫該部分。圖表可由使用者調整版面。

**第一期範圍（本 spec）**
- 匯入 PDF → AI 產生結構化筆記
- 區塊式編輯器，手動編輯
- 選取 → 右側聊天欄討論 → AI 直接覆蓋修改，可復原
- 四種圖表區塊：數據圖、概念圖、論文原圖、白板
- 圖表版面調整：寬高、上下間距、並排（2–3 欄）、對齊

**明確不做（後續版本）**
- 投影片產生與匯出（第二期，另立 spec）
- 拖動圖表內部元素
- 多人協作、雲端部署
- 直接打 API（本期只用本機 CLI）

**成功標準**
1. 匯入一篇真實論文，5 分鐘內得到含各節、ELI5 框與至少一張圖的筆記。
2. 選取任一段落下指令，AI 改寫後正確套用，一次 Ctrl+Z 可完整撤回。
3. 任一圖表區塊可拖曳改寬高、改間距、與另一區塊並排，重新開啟後版面保留。
4. AI 回傳格式錯誤時，筆記內容不被破壞。

## 2. 架構

本機執行的網頁 app。

```
瀏覽器 (React + Vite + TypeScript + BlockNote)      本機 Python (FastAPI)
┌───────────────┬────────────┐                   ┌────────────────────────┐
│  筆記編輯區     │ 右側聊天欄   │ ──HTTP/JSON──▶    │ ai_runner   → claude -p │
│ (區塊 + 圖表)   │            │ ◀──────────────   │             → codex exec│
└───────────────┴────────────┘                   │ pdf_service → PyMuPDF   │
                                                   │ storage     → 本機檔案   │
                                                   │ schema      → 區塊驗證   │
                                                   └────────────────────────┘
```

**後端模組（各自單一職責、可獨立測試）**

| 模組 | 職責 | 依賴 |
|---|---|---|
| `storage` | 論文資料夾讀寫、快照建立與還原 | 檔案系統 |
| `schema` | 定義並驗證區塊 JSON（pydantic） | 無 |
| `pdf_service` | 從 PDF 擷取圖片到 `figures/`，回傳圖片清單（頁碼、檔名） | PyMuPDF |
| `ai_runner` | 以 subprocess 呼叫 claude / codex，處理逾時、取回輸出 | CLI |
| `ai_tasks` | 組 prompt、呼叫 ai_runner、驗證、失敗重試一次 | ai_runner, schema |
| `api` | FastAPI 路由；長任務以 job + 輪詢回報進度 | 以上全部 |

**資料夾結構（每篇論文一個）**
```
papers/<slug>/
  paper.pdf
  figures/        PyMuPDF 擷取的原圖
  summary.md      匯入時產生的論文重點摘要（後續對話用，避免重讀 PDF）
  note.json       筆記本體：區塊陣列
  history/        每次 AI 修改前的 note.json 快照（時間戳命名）
  chat.jsonl      聊天紀錄（含每則 AI 修改對應的快照檔名）
```

## 3. 區塊資料模型

`note.json` 為區塊陣列。所有區塊共有：`id`、`type`、`layout`（選填）。

`layout`：`{ widthPct: 10–100, heightPx?: number, marginTopPx, marginBottomPx, align: "left"|"center"|"right" }`

並排以 `columns` 容器區塊表示：`{ type: "columns", columns: [{ widthPct, blocks: [...] }] }`，2–3 欄。

| type | 內容欄位 |
|---|---|
| `heading` | `level`, `text` |
| `paragraph` | `text`（行內 markdown：粗體、斜體、連結、行內公式） |
| `eli5` | `text` |
| `chart` | `spec`（Vega-Lite JSON）、`source`（例如 "Table 2, p.7"）、`verified: bool` |
| `diagram` | `mermaid`（原始碼） |
| `figure` | `path`（相對於 figures/）、`caption`、`page` |
| `whiteboard` | `scene`（Excalidraw scene JSON） |
| `columns` | 見上 |

前端 BlockNote 文件與此 JSON 之間做雙向轉換（`noteToEditor` / `editorToNote`），此轉換為獨立模組並有單元測試。

## 4. 編輯器與版面

- 編輯器：BlockNote（基於 TipTap），提供拖曳把手、斜線選單、行內格式。
- 自訂區塊：`chart`（vega-embed 渲染）、`diagram`（mermaid → SVG）、`figure`（img）、`whiteboard`（嵌入 Excalidraw，元件內可直接畫）、`eli5`（底色提示框）。
- 版面操作：
  - 拉大小：hover 顯示右下角把手，拖曳改 `widthPct` / `heightPx`，圖表重繪。
  - 調間距：區塊下緣細線上下拖曳改 `marginBottomPx`。
  - 並排：區塊拖到另一區塊左／右側形成 `columns`；欄間分隔線可拖曳改欄寬。
  - 對齊：寬度 < 100% 時可選左／中／右。
- 自動存檔：編輯停止 1 秒後 PUT `note.json`。
- 復原：手動編輯用編輯器原生 undo；一次 AI 修改為單一 undo 步驟；另外聊天欄每則 AI 修改旁有「還原到此修改前」（從 `history/` 快照還原）。

**待規劃階段驗證**：BlockNote 多欄功能位於其 XL 套件，確認授權條款；若不適用，改以自訂 `columns` 區塊＋CSS grid 實作。

## 5. AI 互動

**呼叫方式**
- Claude：在論文資料夾內以 `claude -p` 執行，僅允許讀檔工具；要求輸出 JSON。
- Codex：`codex exec -s read-only -C <論文資料夾> --output-schema <schema.json> -o <輸出檔>`。
- 具體 CLI 旗標（Claude 的工具限制、輸出格式）於實作計畫階段逐一實測後寫入，不憑記憶。
- 聊天欄有下拉選單選 Claude / Codex，預設 Claude。

**匯入流程**
1. 上傳 PDF → 存 `paper.pdf` → `pdf_service` 擷取圖片。
2. AI 任務一：產生 `summary.md`。
3. AI 任務二：依 summary、PDF 與圖片清單產生區塊陣列，骨架：研究動機與問題 → 方法 → 實驗設定 → 結果 → 限制 → 討論問題；每節附一個 `eli5` 區塊；適合處放 `chart` / `diagram` / `figure`。
4. 驗證通過 → 寫入 `note.json`。

**選取修改流程**
1. 使用者選取文字或區塊，聊天欄顯示選取摘要。修改單位一律是「整個區塊」：只選段落中一句時，送出該區塊並以 `selectedText` 標明被選的那句，AI 回傳的是改寫後的整個區塊。
2. 送出內容：使用者訊息、選取區塊 JSON、前後各一個區塊、`summary.md`。
3. AI 回傳二選一：`{ "reply": "...", "replace": null }`（只討論）或 `{ "reply": "...", "replace": [區塊...] }`（修改）。
4. 若有 `replace`：驗證 → 建快照到 `history/` → 取代選取區塊 → 新區塊短暫高亮。
5. 修改期間，被選取區塊鎖定不可編輯。

**ELI5**：Claude 的 prompt 指示使用使用者 `~/.claude` 中的 eli5 skill（對象：大學部同學）；Codex 無 skill，將 ELI5 寫作準則直接寫入 prompt。

## 6. 錯誤處理

| 狀況 | 處理 |
|---|---|
| CLI 未安裝或未登入 | 啟動時檢查，右上角紅燈並顯示修復命令 |
| AI 執行逾時（上限 5 分鐘） | 中止子程序，聊天欄顯示可重試 |
| 回傳 JSON 不合 schema | 附錯誤訊息自動重試一次；仍失敗則在聊天欄顯示原文，筆記不動 |
| 數據圖數字可能錯誤 | 每張 `chart` 顯示 `source`；新產生的圖 `verified=false`，顯示黃色「AI 抽取，待核對」標籤，使用者點擊確認後移除 |
| 存檔失敗 | 顯示錯誤，保留前端狀態，不覆蓋本機檔 |

## 7. 測試

- 後端 pytest：`schema` 驗證（合法／非法區塊）、`storage` 讀寫與快照還原、`ai_tasks` 的重試邏輯——以假 CLI 腳本替代真 AI，不耗額度。
- 前端 Vitest：`noteToEditor` / `editorToNote` 來回轉換不失真。
- Playwright 端對端（假 AI）：匯入範例 PDF → 筆記出現 → 選取段落送出 → 內容被取代 → Ctrl+Z 還原 → 拖曳圖表改寬度 → 重新整理後版面保留。
- 最終以一篇真實論文手動跑一次，對照第 1 節成功標準。

## 8. 技術選型摘要

| 層 | 選擇 |
|---|---|
| 前端 | React + Vite + TypeScript、BlockNote、vega-embed、mermaid、@excalidraw/excalidraw |
| 後端 | Python 3 + FastAPI + pydantic、PyMuPDF |
| AI | 本機 `claude` CLI、`codex` CLI（使用者既有訂閱） |
| 儲存 | 本機檔案（`papers/`） |
