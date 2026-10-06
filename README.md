<h1 align="center">EasyRead 繁體中文版</h1>
<p align="center"><b>讓你更舒服地讀論文，介面與譯文都是繁體中文（台灣用語）</b><br>
匯入 PDF，背景逐頁翻譯；公式、表格照原文排好，隨時對照原文，邊讀邊劃線、記筆記、提問。本地執行。</p>

<p align="center"><b>本版說明</b> · <a href="README.zh-TW.md">完整使用說明（繁體）</a> · <a href="README.zh-CN.md">簡體（上游原文）</a> · <a href="README.en.md">English</a></p>

> 本專案是 [Edwardxlai/easyread](https://github.com/Edwardxlai/easyread)（MIT 授權）的**繁體中文衍生版**，**不是上游官方版本**。使用上的問題請先在本倉庫處理，不要向上游回報。

## 和上游不一樣的地方

1. **繁體中文（台灣用語）介面**：設定裡的「界面語言」新增「繁體中文」，系統語言是繁體時會自動選用。詞條由 OpenCC 轉換後逐條人工複核台灣用語（軟體、檔案、設定、匯入／匯出、預設、資訊…）。
2. **繁體中文譯文**：「論文譯成」新增「繁體中文（台灣用語）」，**預設就是繁體**；問 AI、整理筆記的回答也會用繁體。
3. **筆記可以放圖片**：貼上截圖、選檔案上傳、拖放都可以（PNG／JPEG／WebP／GIF，單檔 ≤10 MB，不收 SVG）。圖片存在該論文自己的資料夾；匯出 Markdown 時若含圖片會輸出 zip（`notes.md` 加 `note-images/`），離線 HTML 會內嵌圖片。
4. **匯出帶劃線的 PDF**：把你在網頁上的劃線、底線（含筆記內文）寫成標準 PDF 註解，另存成**新的 PDF 副本**，原檔不會被改。閱讀頁的「匯出筆記」對話框有入口，也可以用 `easyread export-pdf <論文ID> --out 路徑`。中文譯文上的劃線會對應到整句英文，英文上的劃線盡量精確，沒有句子對齊的段落則標整段；找不到對應位置的劃線會明確回報、不會悄悄略過。這是一次性匯出，不是即時同步。目前只在 PDFium 渲染驗證過，macOS 預覽程式、Acrobat 未實測。
5. **漏段偵測**：上游在「同一段落跨頁」時，兩批翻譯的交接可能讓整段原文沒進任何區塊。`easyread check <論文ID>` 會列出疑似漏掉的段落，翻譯完成時任務日誌也會提示。**只偵測，不自動補翻。**
6. **本機服務安全加固**：
   - 所有請求檢查 `Host`，只接受 `127.0.0.1`、`localhost`、`[::1]` 加實際埠號，防 DNS rebinding；`Origin` 改用白名單。
   - 設定 API 對 `claude`／`codex` 的 `command` 與 `extra_args` 做白名單，擋掉「改設定即可讓伺服器執行任意程式」的路徑。

7. **配色**：「設定 → 閱讀」新增「配色」，淺色與深色模式各自獨立，可選現成配色（淺色 6 組、深色 5 組）或自訂背景色與文字色，其餘顏色自動衍生；文字與背景對比度低於 4.5:1 會警告、低於 3:1 禁止儲存。目前只調背景與文字，強調色與螢光筆顏色沒動。
8. **原頁定位修復**：上游在「跨頁段落」時，右側原頁面板的黃框可能框到錯誤位置（例如框到作者名單）。本版改為沿段落文字比對找出本頁的真正結尾；舊論文打開時會自動重新定位。跨頁段落仍只框出段首所在的那一頁。

## 快速開始（從原始碼）

需要 **Python 3.10 以上**（macOS 內建的 3.9 不行，可用 `brew install python@3.12`）。

```bash
git clone https://github.com/gut2003817/PaperNote.git easyread-zhtw
cd easyread-zhtw
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m easyread serve --open
```

- 瀏覽器會開啟 `http://127.0.0.1:8765`。請用 `127.0.0.1` 或 `localhost` 連線；用區網 IP 或其他網域名稱會被 403 拒絕。
- 介面語言預設跟隨系統；若系統語言不是繁體，第一次請到「設定 → 閱讀 → 界面語言」選「繁體中文」，之後會記住。頂欄右上角的 `EN`／`中` 按鈕可以隨時切換中英介面。
- **不要用環境變數 `EASYREAD_LANG` 啟動日常使用的服務**：它是除錯用，會強制鎖定介面語言、**優先於設定**，頂欄的 `EN` 按鈕按了會看起來完全沒反應（設定其實有存，但被環境變數蓋過）。
- 命令列用 `.venv/bin/python -m easyread <指令>`（`list`、`check`、`translate`、`blocks`、`locate`…），`easyread` 沒有裝在全域。
- 翻譯引擎預設用本機的 Claude Code CLI，**不用 API Key，但會消耗你的訂閱額度**；也可以改用 Codex、各家 API 或本機 Ollama，見 [完整使用說明](README.zh-TW.md)。

## 已知限制

- 跨頁段落漏譯是上游的 bug，本版**只偵測、沒有根治**；偵測的誤報率只在一篇論文上驗證過。
- 本版**移除了上游的 GitHub Actions 設定**（`.github/workflows/` 的 `release.yml`、`test.yml`），所以沒有自動測試與自動打包安裝包；測試請在本機執行 `.venv/bin/python -m pytest tests -q`。
- ASD-STE100 問答模式的提示詞寫死「只輸出中文」，不看譯文語言。
- `docs/`、`skill/` 內的文件仍是簡體。
- **桌面版（Electron）與上游的安裝包沒有針對本版驗證**，請從原始碼執行。IPv6（`[::1]`）也只驗證了 Host 標頭會被接受，沒有真的走 IPv6 連線。
- 若你把 `config.json` 的 `command` 手改成檔名不是 `claude`／`codex` 的自訂 wrapper，翻譯與問 AI 會被擋下並提示欄位。
- 尚未處理：`openai.base_url` 可被改成他人網址（API Key 會被帶走）、`/api/library/move` 接受任意目錄、token 仍由 GET 回傳且不輪換。

## 變更紀錄與授權

- 本版的改動見 [CHANGELOG.md](CHANGELOG.md) 最前面「未發布」。
- 授權為 **MIT**，沿用上游的 [LICENSE](LICENSE)（Copyright (c) 2026 LiangXiLin）；本版的修改部分同樣以 MIT 釋出。
- 感謝上游作者與貢獻者做出 EasyRead。
