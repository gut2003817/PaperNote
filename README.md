# Paper Notes

本機執行的論文筆記工具。上傳一篇論文 PDF，AI 會把它整理成「報 paper 用」的筆記：每段附白話解釋（ELI5）、從論文抓數字畫成數據圖、用概念圖說明方法、直接引用論文原圖。之後可以選取任何一段，在右側聊天欄跟 AI 討論，AI 會直接改寫那一段；圖表可以拖曳調整大小、間距與並排。

AI 透過你電腦上已登入的 **Claude Code** 與 **Codex CLI** 呼叫，使用你自己的訂閱額度，不需要 API key。

## 功能

- **一鍵整理論文**：依「研究動機與問題 → 方法 → 實驗設定 → 結果 → 限制 → 討論問題」產生筆記，每段至少一個白話解釋框。
- **四種圖**：
  - 數據圖（Vega-Lite）：數字直接取自論文並標註出處，新產生的圖會掛「AI 抽取，待核對」標籤，提醒你對過原文。
  - 概念圖（Mermaid）：方法流程、架構。
  - 論文原圖：自動擷取 PDF 內的圖片，另附每頁整頁截圖（向量圖也抓得到）。
  - 白板（Excalidraw）：自己畫。
- **選取 → 討論 → AI 直接改寫**：點選或反白任一段，在右側輸入指令（「改得更白話」、「加一張比較圖」），AI 直接替換內容；只是提問時 AI 只回答、不動筆記。
- **可復原**：每次 AI 修改都是一個復原步驟（⌘/Ctrl+Z），聊天欄也能「還原到此修改前」。
- **版面調整**：拖右下角改大小、拖下緣改間距、把區塊拖到另一區塊左右兩側即可並排（2–3 欄），可切換靠左／置中／靠右。
- **Claude／Codex 可切換**：匯入與每次討論都可以選要用哪一個。

## 需求

| 項目 | 版本 |
|---|---|
| Python | 3.12 以上 |
| Node.js | 20 以上 |
| Claude Code CLI（`claude`） | 已登入（`claude auth status`） |
| Codex CLI（`codex`） | 選用，已登入（`codex login status`） |

兩個 CLI 至少要有一個；右上角燈號會顯示它們是否可用，不可用時會直接顯示修復指令。

## 安裝

```bash
git clone https://github.com/gut2003817/PaperNote.git
cd PaperNote

# 後端（請用 3.12 以上的 Python，例如 Homebrew 的 python3.12）
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cd ..

# 前端
cd frontend
npm install
cd ..
```

## 啟動

```bash
./dev.sh
```

會同時啟動後端（http://127.0.0.1:8000）與前端（http://localhost:5173），並自動開啟瀏覽器。若右上角顯示「後端未啟動」，等一兩秒重新整理即可。按 Ctrl+C 結束。

## 使用流程

1. 首頁選擇論文 PDF，標題可留空，選擇 Claude 或 Codex，按「開始整理」。一般論文約 1–3 分鐘。
2. 點選或反白筆記中想討論的內容，右側會顯示「已選取」。
3. 在右側輸入指令，按 ⌘/Ctrl+Enter 送出。AI 處理期間筆記會暫時鎖定。
4. 不滿意：在筆記裡按 ⌘/Ctrl+Z，或在聊天紀錄點「還原到此修改前」。
5. 數據圖對過論文原文後，點一下黃色標籤確認。
6. 在筆記中輸入 `/` 可以插入：白話解釋、數據圖、概念圖、論文原圖、白板、多欄。

修改會在停止輸入 1 秒後自動存檔。

## AI 用量

- 後端在本機呼叫 `claude -p` 與 `codex exec`，計入你的 Claude 訂閱與 ChatGPT／OpenAI 帳號額度；只要環境中沒有設定 `ANTHROPIC_API_KEY`／`OPENAI_API_KEY`，就不會產生 API 費用。
- Claude 固定使用 **Sonnet** 模型（不受 Claude Code 全域 `/model` 設定影響）。
- 匯入一篇論文 = 2 次 AI 呼叫（摘要 + 筆記）；每次討論或修改 = 1 次。
- AI 只能讀檔，不能寫檔；所有 AI 輸出都先經過格式驗證才會進入筆記，格式錯誤會自動重試一次，仍失敗則顯示原始輸出、筆記不變。

## 專案結構

```
backend/            FastAPI + pydantic + PyMuPDF
  paper_notes/
    schema.py       筆記區塊格式（note.json 的唯一定義）
    storage.py      論文資料夾讀寫、快照、聊天紀錄
    pdf_service.py  擷取 PDF 圖片
    ai_runner.py    呼叫 claude / codex CLI
    ai_tasks.py     prompt、驗證、重試
    api.py          HTTP 路由
frontend/           React + Vite + TypeScript + BlockNote
  src/convert/      note.json ↔ 編輯器區塊轉換
  src/editor/       自訂區塊（圖表、概念圖、原圖、白板、白話框）與拖曳版面
  src/chat/         右側聊天欄
docs/superpowers/   設計規格與實作計畫
```

## 資料位置

每篇論文一個資料夾，放在 `papers/<代號>/`（已排除在 git 之外）：

| 檔案 | 內容 |
|---|---|
| `paper.pdf` | 原始論文 |
| `figures/` | 擷取出的圖片與整頁截圖 |
| `summary.md` | AI 整理的論文摘要（後續討論用，避免每次重讀整篇 PDF） |
| `note.json` | 筆記本體 |
| `history/` | 每次 AI 修改前的快照 |
| `chat.jsonl` | 聊天紀錄 |

可用環境變數 `PAPER_NOTES_DATA` 指定其他資料夾。

## 測試

```bash
cd backend && .venv/bin/pytest -q                 # 後端
cd frontend && npx tsc --noEmit && npx vitest run # 前端
cd frontend && npx playwright test                # 端對端（用假 AI，不耗額度）
```

## 已知限制

- 同一篇筆記開兩個分頁會互相覆蓋（以最後存檔為準）。
- 文字顏色、對齊、底線等格式不會保存；白板中貼上的圖片不會保存。
- 修改後 1 秒內重新整理或關閉頁面，該次修改可能遺失。
- 尚未支援匯出投影片（規劃中的第二期）。

## 授權注意

前端的多欄功能使用 `@blocknote/xl-multi-column`，授權為 GPL-3.0（或商業授權）。若公開散布本專案，需以 GPL-3.0 相容授權釋出。
