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
