# 同步上游 EasyRead v1.4.4 報告

分支：`sync/upstream-v1.4.4`（worktree `/Users/ting/easyread-zhtw-sync`），尚未合回 main，也沒有 push。

- 上游：`4d00a94`（v1.4.4），與我們的共同祖先是 `1fef04f`（v1.3.2 之後一個 docs commit），中間有 143 個上游 commit。
- 我們這邊起點：main `bc66b79`。同步進行中 main 前進到 `ca864e6`（AI 示意圖兩個 commit），已再合進本分支，所以本分支可以直接快轉合回目前的 main。
- 兩個合併 commit：`176c970`（合入上游 v1.4.4）、`aedd309`（合入 main 的 `ca864e6`）。

## 一、上游新增了什麼（使用者看得到的部分）

**閱讀與原頁**
- 右側 PDF 原頁可以選字、複製（v1.4.4 起複製會保留空格與換行）；原頁可以縮放 50%–300%、適合寬度。
- 記住閱讀位置；關掉「跟隨」後再打開，會立刻對回目前閱讀的位置。
- 閱讀頁搜尋原文與譯文（Ctrl／⌘＋F）、書籤、筆記跳轉。
- 多級目錄逐級縮排；標題裡的公式在文獻庫與閱讀頁都會渲染。
- 正文裡的原文超連結會補回來。

**翻譯品質**
- 自動略過空白頁（不送翻譯，不花額度）。
- 腳註獨立：`[^13]` 是腳註、`[13]` 是參考文獻，點了會跳到對的地方。
- 偵測裸露的 TeX（少了 `$`）並要求模型修正；翻譯改成完整收完串流再存，斷流會自動恢復。
- 跨頁、跨欄的續文不再被當成圖片標籤吃掉；原頁定位改為「多個實測區域」（跨欄、跨頁的段落框得更準）。
- 新增「自訂翻譯要求」（設定裡填，之後的翻譯和重譯都會套用）。
- 譯文語言新增英語、義大利語（原文不是英文時也能譯成英文）。

**標註與筆記**
- 獨立公式也能劃線；劃線直接沿用上次的顏色；標註可復原／重做（Ctrl＋Z／Ctrl＋Y）。
- 筆記可以「關聯圖表」，在筆記裡展開看圖。
- 「問 AI」可以貼上圖片（PNG／JPEG／WebP）。

**文獻庫與匯入**
- 從 Zotero 整庫遷移、匯入整個資料夾（資料夾層級變分類）、分類可以分層。
- 可以「連結本機 PDF」而不複製檔案。
- 匯出手機版 HTML（`easyread export ID --mobile`）。
- 一次停止所有翻譯；選幾頁翻譯；單篇資料檔損壞不再讓整個文獻庫載入失敗。

**模型**
- 新增 CodeBuddy CLI、Grok Build、Antigravity CLI、Cursor CLI 引擎；可以儲存自訂 API 接口。

**程式結構（看不到，但影響合併）**
- 上游把 `easyread/` 底下的模組全部搬進子套件：`app/`、`chat/`、`engines/`、`export/`、`library/`、`pdf/`、`server/`、`translate/`，另有新的 `bulk/`、`zotero/`。測試也分到 `tests/<子套件>/`。

## 二、衝突清單與解法

第一次合併（上游 v1.4.4）有 34 個衝突檔；第二次合併（main 的 `ca864e6`）有 2 個。

| 檔案 | 衝突原因 | 解法 |
|---|---|---|
| `.github/workflows/release.yml`、`test.yml` | 我們刪了、上游改了 | 維持刪除（token 沒有 workflow 權限） |
| `tests/test_langs.py` | 我們改了、上游搬到 `tests/translate/test_langs.py` | 刪舊檔；上游的兩個 zh-Hant 測試改成「zh-Hant 是 zh-TW 的別名」的期望值 |
| `README.md` | 我們整份換成繁體版說明 | 保留我們的版本；`README.zh-CN.md`（上游原文）更新成上游新版，語言列維持我們的版本 |
| `CHANGELOG.md` | 兩邊都在檔頭加段落 | 我們的「未發布」放最上面並加一條「合入上游 v1.4.4」，下面接上游 v1.4.4…v1.3.3 |
| `easyread/app/i18n.py` | 我們加 zh-TW 介面，上游加 zh-Hant 介面 | 見第三節；採用上游較細的系統語言判斷（`zh-Hans-HK` 判成簡體），但結果回傳 `zh-TW` |
| `easyread/translate/langs.py` | 我們加 zh-TW 譯文，上游加 zh-Hant、en | 三個都保留：`zh`、`zh-TW`、`en`；`zh-Hant` 當 `zh-TW` 的別名 |
| `easyread/translate/prompts.py`、`prompts_en.py` | 我們的台灣用語範例與引號替換、上游的 `_HANT`／英文目標 | 保留我們的 `_TW_*_SWAP` 與 `TW_STYLE`，也保留上游的英文目標規則；上游的 `_HANT` 不用 |
| `easyread/app/config.py` | 預設譯文語言、新設定項 | 預設譯文仍是 `zh-TW`；保留 `obsidian_vault`，加上上游的 `translation_instructions` |
| `easyread/chat/chat.py` | 我們加 `reply_note`，上游加 XRAY 回答方式 | 兩者都保留，`reply_note` 接在任何回答方式後面 |
| `easyread/server/server.py` | Host/Origin 白名單、筆記圖片、匯出劃線 PDF、Obsidian 端點，對上上游把 `_chat` 拆出去、加 chat-media 路由 | 都保留；`_chat` 改用上游的 `chat_handler`；聊天置頂／改名／刪除改走上游的 `paper_api` |
| `easyread/pdf/pdfwork.py` | 我們的 `_crop_image`／`crop_png`（Obsidian 截圖用）、`LOCATE_VERSION` | 保留我們的寫法，改用上游的 `Workspace(root).source_pdf`（支援連結本機 PDF）；`LOCATE_VERSION = "10z1"` |
| `easyread/export/build.py` | 筆記圖片打包、上游手機版略過已譯頁 | 兩者合併 |
| `easyread/app/cli.py` | `export-pdf` 子命令、上游 `export --mobile` | 兩者都保留 |
| `easyread/app/prefs.py`、`engines/engines.py`、`library/checks.py`、`server/jobs.py`、`server/settings_api.py`、`translate/translate.py`、`server/library_api.py` | 匯入路徑（上游搬家）＋我們的模組 | 改成新路徑，保留 `palette`、`cli_guard`、`coverage`、`obsidian_*`；資料夾選擇器同時支援上游的自訂標題與我們的「選擇 Obsidian 資料夾」 |
| `easyread/web/i18n/en.json` | 兩邊都在檔尾加詞條 | 聯集；刪掉一個重複鍵「繁体中文」；更新提示的詞條改用上游版本（舊的兩條已沒人用） |
| `easyread/web/js/common/i18n.js`、`util.js`、`settings-tabs.js` | 介面語言、譯文語言清單 | 介面：簡體／繁體（zh-TW）／英文；譯文：簡體、繁體（zh-TW）、英語、日、韓、西、法、德、義；保留 Obsidian 與配色區塊 |
| `easyread/web/js/common/settings.js` | 我們的 `after()` 回呼、上游保留捲動位置 | 兩者都做 |
| `easyread/web/js/reader/margin.js`、`notespanel.js` | 筆記插圖按鈕、上游「關聯圖表」 | 兩個按鈕都在；失焦收起筆記時同時等「上傳圖片中」和「選圖表中」 |
| `easyread/web/css/reader.css`、`settings.css`、`library.html` | 兩邊各加樣式／腳本 | 聯集 |
| `electron/main.cjs` | 繁體啟動錯誤訊息、上游資料目錄準備 | 兩者都保留 |
| `tests/app/test_i18n.py` | 系統語言期望值 | 繁體地區期望 `zh-TW`；上游的繁體詞典測試改成檢查 `zh-TW` |
| 第二次合併：`easyread/obsidian_note.py`、`easyread/server/server.py` | 匯入路徑、`ai_images` 參數 | 新路徑＋保留 `ai_images` |

**沒有衝突但需要另外修的地方**
- 我們新增的模組（`cli_guard`、`coverage`、`note_images`、`obsidian_*`、`palette`、`pdf_annotate`）留在 `easyread/` 頂層，只改匯入路徑；我們的 14 個測試檔也只改匯入路徑與 mock 目標，測試內容沒動。之後若想跟上游一樣分進子套件，可以另開分支做。
- `easyread/web/js/common/markup.js`：上游新增 Markdown 連結 `[文字](網址)` 語法，會先把 `![](note-images/…)` 的方括號部分吃掉，筆記圖片變回純文字。已讓連結語法跳過前面有 `!` 的情況；`tests/test_note_images.cjs` 和上游的 `tests/web/test_markup.cjs` 都通過。
- `scripts/zhtw_overrides.json`：重新產生 zh-TW.json 時，原本手調過的 6 條 Obsidian 詞條會被 OpenCC 結果蓋掉，所以把它們寫進 overrides；另外修正 9 條 OpenCC 轉得不好的新詞條（例如「聯絡維護者」被誤轉成「關聯維護者」、「原文本來」被斷成「原文字來」、「當前」改「目前」、「訪問」改「存取」）。

## 三、zh-Hant 與 zh-TW 的處理

上游 v1.4.3 自己加了繁體：介面代碼 `zh-Hant`（詞典 `zh-Hant.json`），譯文代碼 `zh-Hant`（提示詞「繁体中文（正體中文）」加一條用字要求）。我們早就有 `zh-TW`（台灣用語、引號「」、範例換成繁體）。

做法：**`zh-TW` 是唯一正式代碼，`zh-Hant` 當別名。**
- 介面：`LANGS = ("zh", "zh-TW", "en")`；設定、`EASYREAD_LANG`、系統語言裡出現 `zh-Hant`，一律當成 `zh-TW`，頁面 `<html lang="zh-TW">`，用 `zh-TW.json`。上游的 `zh-Hant.json` 已刪除（我們的詞典品質較好：台灣引號、雲端硬碟、帳號、螢光筆等用詞；兩份詞典有 105 條不同）。
- 譯文：`langs.valid()`、`of_paper()`、`remember()`、`reply_lang()` 都先把 `zh-Hant` 轉成 `zh-TW`，所以設定、匯入參數或論文 meta 裡的 `zh-Hant` 會走台灣用語提示詞，不會掉回簡體。
- 舊資料不用遷移：她的 `prefs.json`（`ui.lang=zh-TW`）、`config.json`（`target=zh-TW`）、已翻譯論文的 `meta.target=zh-TW` 都照常可用。
- 實測：把 `prefs.json` 的 `ui.lang` 設成 `zh-Hant`，首頁仍回 `<html lang="zh-TW" data-lang-choice="zh-TW">`。

## 四、待使用者決定

1. **（資安，優先）上游新增的 CLI 引擎繞過了我們的 `cli_guard`。** 我們封住了 claude／codex 的 `command`／`extra_args`，但上游新加的 CodeBuddy、Grok Build、Antigravity、Cursor 也是從設定讀 `command` 和 `extra_args` 來啟動子程序。實測 `settings_api.save_config({"codebuddy": {"command": "/bin/sh", "extra_args": ["-c", "id"]}})` 會被接受並寫入（grok、cursor 也一樣；claude 會被擋）。也就是說，拿到 token 的人又能透過設定 API 讓伺服器執行任意程式。這次合併沒有修，因為每個 CLI 該放行哪些參數需要逐一判斷；建議交給正在做 `fix/security-hardening` 的工作，把 `cli_guard.NAMES` 與參數白名單擴充到這四個引擎（最保守的做法是先完全拒絕這些區段的 `command`／`extra_args`）。
2. **原頁定位會重算一次。** `LOCATE_VERSION` 從 `5z1` 變 `10z1`，每篇論文第一次打開時會重算 `layout.json`（不呼叫 AI、不花額度）。上游的新定位（`text_regions.locate_prose`）現在先處理段落與清單，我們的 `_walk_end` 跨頁修正變成它找不到時的後備，以及標題等其他區塊用。之前她確認過的黃框（例如論文 113cd3c64e79 的 p1-5）建議合回 main 後再看一次。
3. **`easyread` 命令列入口改了。** pyproject 的入口從 `easyread.cli:main` 變成 `easyread.app.cli:main`。她平常用 `.venv/bin/python -m easyread serve --open`，不受影響；若有用 `.venv/bin/easyread`，合回 main 後要在 main 的 `.venv` 重跑一次 `pip install -e .`。
4. **譯文下拉選單裡「簡體中文」的名稱。** 上游把 `zh` 的顯示名改成「简体中文」（我們原本叫「中文」），按鈕上仍顯示「翻譯成中文」→ 在繁體介面是「翻譯成簡體中文」（我們之前的 override）。若想改回別的說法再調。
5. **新模組要不要搬進子套件。** 目前我們的模組留在 `easyread/` 頂層，功能正常；要和上游的結構一致可以另外做，但之後每次同步都比較省事的方向是搬。
6. **上游 CSS 的 `html[lang="zh-Hant"]` 規則沒刪。** 我們不會產生這個 lang，保留只是為了以後同步少衝突；繁體字型由我們原本的 `html[lang="zh-TW"]` 規則處理。

## 五、驗證結果

1. **測試數字**
   - 合併前，main `bc66b79`：`567 passed, 1 skipped, 701 subtests passed`。
   - 同步途中 main 前進到 `ca864e6`，用匯出的副本補跑：`599 passed, 1 skipped, 708 subtests passed`。
   - 合併後，本分支：`813 passed, 1 skipped, 872 subtests passed`（含上游新增測試；用 main 的 `.venv`，`PYTHONPATH` 指向本 worktree，已確認 `easyread.__file__` 指向 sync 版本）。
   - 前端與桌面的 node 單元測試（`tests/*.cjs`、`tests/web/*.cjs`、`tests/desktop/*.cjs`，不含需要瀏覽器的 `e2e.cjs`）：34 個檔全過。
2. **`git diff main..sync/upstream-v1.4.4 --stat`**：332 個檔案，+12609／−1724，其中 106 個是搬家（rename）。客製功能都還在，用 grep 確認過：預設譯文 `"target": "zh-TW"`、`TARGETS["zh-TW"]`、`LANGS = ("zh", "zh-TW", "en")`、`LOCATE_VERSION = "10z1"`、`_walk_end`、`parse_request`／`_host_ok`、`cli_guard.check_*`（engines、settings_api、chat_models）、jobs kind `"obsidian"`、端點 `note-image`／`notes-zip`／`annotated-pdf`／`obsidian-note`、`TW_STYLE`／`note_style`、`coverage.find_gaps`、`palette`、`export-pdf`、`.github/workflows` 不存在；對應測試（`test_hostcheck`、`test_cli_guard`、`test_coverage`、`test_note_images`、`test_pdf_annotate`、`test_palette`、`test_locate_crosspage`、`test_obsidian_*`、`test_note_style`、`test_i18n_zhtw.cjs`）全過。
3. **詞典鍵比對**：`en.json` 1444 個鍵，`zh-TW.json` 1444 個鍵，缺漏 0、多出 0、空值 0。zh-TW.json 由 `scripts/gen_zhtw.py` 用 OpenCC s2twp 重新產生（OpenCC 只裝在 scratchpad 的臨時 venv，沒有加進 pyproject）。
4. **實際啟動**：用暫存資料目錄（`EASYREAD_HOME` 指到 scratchpad）在 8798 埠啟動；`GET /` 回 200，`<html lang="zh-TW" data-lang-choice="auto" data-target="zh-TW">`，有注入 `pr-i18n` 詞典；`GET /api/library` 回 200；`Host: evil.example` 回 403。結束時只停掉自己記下的 PID，8765 的服務沒動。過程中沒有觸發翻譯或 AI 呼叫。

**一件要誠實說明的事**：合併過程中我用一段「逐一匯入所有模組」的指令檢查匯入路徑，不小心匯入了 `easyread.__main__`，啟動了一個服務（127.0.0.1:61188，資料目錄是 worktree 本身，沒有碰到她的文獻庫），可能也在瀏覽器開了一個分頁。約兩分鐘後我依 PID 停掉它，並刪掉它在 worktree 裡產生的 `library/`、`.server.json`、`easyread.log`、`update.json`、`.models-seen.json`（都在 .gitignore 裡）。它有向 GitHub 查了一次新版本，沒有呼叫任何 AI。
