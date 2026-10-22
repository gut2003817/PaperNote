# 一鍵寫進 Obsidian：設計文件

日期：2026-10-22　狀態：待使用者核可（尚未實作）

## 1. 目的與為什麼

使用者（高筠婷）在 EasyRead 讀完一篇論文後，想直接得到一篇可放進 Obsidian 的整理筆記，內容要有根據（來自論文原文與她的劃線），不是 AI 憑空寫的。她的課堂報告要求「幾秒到一分鐘內講出這篇論文有趣的地方」，所以筆記開頭必須先讓人快速知道這篇的價值與最大亮點。

現況：EasyRead 已能匯出 Markdown／zip，但那是前端把她自己寫的筆記打包，不會幫她整理。她既有的匯出筆記（vault 裡的 `6G 自我演進安全框架-筆記/notes.md`）她自己評為不好，原因：標題重複、沒有標籤、圖片難管理（雜湊檔名、各自放在每篇的資料夾）。

## 2. 目標、非目標、反目標

**目標**
- 閱讀頁一顆「寫進 Obsidian」按鈕；按了之後 AI 讀論文與讀者劃線，在她的 vault 新增一篇筆記。
- 筆記開頭有口語化的「30 秒版」，其後是固定結構（見 §4）。
- 圖片：從論文截取重要原圖（A），並可用 Mermaid 畫流程／架構示意（B）。
- 筆記間用標籤好管理、圖片集中好管理。

**非目標（這一期不做）**
- C：AI 繪圖模型生成概念插圖（需要另外的服務與費用）。使用者說 A、B、C 都可以，但設計上先做 A、B，C 另案。**這是我的建議，使用者尚未明確同意延後。**
- 在 Obsidian 裡面呼叫 AI（外掛）。使用者明說「在 EasyRead 按鈕就好」。
- 改動或建立 `.obsidian` 設定、既有筆記、Excalidraw 圖。
- 即時雙向同步。

**反目標（出現就算失敗）**
- 覆蓋任何已存在的檔案，尤其是使用者在「我的想法」補寫的內容。
- 筆記出現論文裡沒有的數據、引用或結論。
- 沒按按鈕就消耗她的 Claude 額度。

## 3. 限制

- 每次按鈕會呼叫 AI（用她的 Claude 額度），只有她按才執行；不自動觸發、不在匯入後自動跑。
- Vault 位置：`/Users/ting/Documents/Obsidian Vault`（已存在、正在使用）。路徑含空格，必須正確處理。
- 筆記寫在 vault 的 `論文筆記/`，圖片寫在 `論文筆記/附圖/`（皆新建資料夾，只有這兩個）。
- 沿用現有技術：Python 標準庫伺服器、無新增第三方依賴、`pypdfium2`＋PIL 已存在。
- 筆記寫作遵循已合併的 zh-TW 筆記寫作規範（`easyread/langs.py` 的 `NOTE_STYLE`）。
- 不改動使用者真實資料：測試一律用暫存目錄，絕不寫入真實 vault，不真的呼叫 AI。

## 4. 使用者已決定的內容

**檔案與結構（一篇論文一個 `.md`）**

1. 最上方 frontmatter（屬性區）：標籤、年份、作者、來源連結（DOI／arXiv／URL）。標籤由 AI 從論文主題產生約 3 到 5 個，使用者之後可自行改。
2. 一個標題（只有一個；作者與來源資訊只放在屬性區，不再重複）。
3. **30 秒版**：口語、像在台上對同學講的開場，句子短、能直接念出來，包含「一句話亮點」與 2 到 3 個「為什麼值得聽」。（長度約 150 字內是我的建議，非使用者指定。）
4. 問題與動機。
5. 方法重點。
6. 結果（最重要的數字與比較）。
7. 我的劃線：她在 EasyRead 劃的句子，附頁碼。
8. 限制與我的想法：「我的想法」留空給她自己補，AI 不替她寫感想；限制可由論文內容整理。

所有內容須來自論文原文；推論須標明是推論。

**圖片**
- A：AI 挑「比較重要的」圖表（不限張數，由重要性決定，例如整體架構圖、主要結果圖），從論文 PDF 截成圖放進筆記。
- B：Mermaid 文字圖（流程圖、方法架構），直接寫在 `.md` 的 ```mermaid 區塊，不產生圖檔。
- 所有圖檔放同一個資料夾 `論文筆記/附圖/`，檔名為「論文簡稱＋圖號＋一句描述」，例如 `6G-SAGIN-圖2-整體架構.png`，不使用雜湊檔名。

**重複按按鈕**
- 預設不覆蓋已存在的檔案；另存新檔，檔名加時間。

## 5. 現有程式事實（2026-10-22 唯讀調查，路徑相對 `easyread/`）

這些是建造者可直接利用的條件，不是需求。

- 論文 `paper.json` 的 blocks 已有 `type:"figure"`／`"table"`，含 `page`、`num`、`box`（頁面歸一化 `[x0,y0,x1,y1]`）、`caption_en/zh`、`src`（`figures/crop-*.webp`）；截圖由 `figures.py`（`figure_box`、`prepare_figures`、`fill`）完成。
- `pdfwork.crop(root, page, box, out_name, scale=3.0)`（`pdfwork.py:102-114`）把區域渲染成圖，**目前只輸出 WEBP**；Obsidian 用的 PNG（或 JPEG）需要新增輸出格式或另寫轉存。
- 引擎共用入口：`notehelp.py` 的 `prompt(ws, mode, note, engine)` 與 `handle()`；非串流呼叫 `engines.run(cfg, prompt, cwd, images, cancel, meter)`；claude 引擎只開 Read 工具、在論文目錄內讀 `paper.json`。視覺（讀圖）：codex 與 openai（需 `vision`）支援，claude 靠自己 Read 圖檔。
- 背景工作：`jobs.Jobs.submit_small(kind, pid, **kw)`，目前 kind 只有 `answer`、`retranslate`；狀態由 `GET /api/jobs?pid=` 查（queued/running/done/error，無百分比）；記錄只在記憶體、重啟消失。逾時預設 claude/codex 1200 秒、openai 600 秒。
- 設定：`config.py` `DEFAULTS` 加鍵（例如 `obsidian_vault`）；`settings_api.save_config` 內驗證（範例：`cli_guard.check_patch`、`palette.validate`）；前端 `web/js/common/settings*.js`；資料夾選擇可重用 `POST /api/library/pick-folder`。vault 路徑適合放 config，不放 prefs。
- 讀者劃線在 `reader.json` 的 `notes`（kind=highlight 等，欄位有 `anchor`、`quote`、`color`、`side`、`body`）。**notes 沒有頁碼**，頁碼要用 `anchor` 查 `paper.json` 的 block 的 `page`。現成可參考 `chat._marks`（內部函式）。
- 論文 meta 在 `paper.json` 的 `meta`（title_zh、title_en、authors、doi、year、date、venue、arxiv、url、abstract_en 等）；使用者覆寫在 `item.json` 的 `meta_override`。
- 路徑安全：沒有現成的「使用者自選目錄」寫入檢查，需自寫：絕對路徑、`resolve()`、拒絕 symlink、必須是既有目錄、拒絕 `..`；POST 需 `X-Token`。目標檔用 `open(..., "x")` 之類避免覆蓋。
- 測試慣例：`tests/test_note_images.py` 的 `ServerCase`（暫存 `EASYREAD_HOME`／`EASYREAD_LIBRARY`、port 0、`X-Token`）；提示詞快照測試見 `tests/test_note_style.py`。
- 調查沒有在 `pdfwork.py`、`figures.py`、`export.js`、`server.py` 找到 Obsidian／Mermaid 相關程式，但未全專案搜尋。

## 6. 留給建造者決定

- 按鈕放在閱讀頁哪裡（例如「匯出筆記」對話框內，或獨立按鈕）；進度與完成提示的呈現。
- 設定頁如何設 vault 路徑（建議在設定頁加欄位，並驗證路徑存在且可寫）。
- 提示詞具體寫法，AI 如何挑圖、如何產生「論文簡稱」與標籤。
- 讓 AI 看圖的方式（claude 引擎讀圖檔；其他引擎見 §5）。
- Mermaid 語法正確性的檢查方式（至少避免產生明顯壞掉的區塊）。
- 檔名清理規則（去除檔名不合法字元、長度限制）、時間戳格式。
- 論文原圖是否需要在筆記中附 caption 與頁碼來源。
- 失敗時的處理與錯誤訊息（vault 路徑不存在、不可寫、AI 逾時、PDF 找不到圖）。

## 7. 驗收（使用者視角與可檢查項）

- 按一次按鈕，vault 的 `論文筆記/` 出現一個 `.md`，Obsidian 能打開，frontmatter 有標籤、年份、作者、來源；只有一個標題。
- 開頭 30 秒版是口語。
- 圖片檔都在 `論文筆記/附圖/`，檔名可讀，筆記裡的圖片連結能在 Obsidian 顯示。
- 再按一次按鈕：舊檔不變，另出現一個帶時間的新檔。
- 沒設定 vault、路徑不存在或不可寫時，給明確訊息且不寫任何東西。
- 自動測試涵蓋：路徑驗證、不覆蓋、檔名、frontmatter、圖片輸出與命名；測試不寫真實 vault、不呼叫真實 AI。
- 效果（筆記好不好）只有使用者實際在一篇論文上試過才算驗證，不能由測試證明。
