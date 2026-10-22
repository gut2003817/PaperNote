# 本機服務資安加固（2026-10-22）

分支：`fix/security-hardening`（從 main `bc66b79` 開出）；已合併進 `integrate/v1.4.4-secure`（基於上游 v1.4.4 同步分支 `sync/upstream-v1.4.4` a641bdf），模組路徑以第 4 節對照表為準。
範圍：先前審計留下的三項本機 API 風險。審計結論是沒有後門，主要風險在本機 HTTP API（`easyread/server.py`，127.0.0.1:8765）。

## 0. 先釐清：現有防護下，誰打得到寫入 API

在這次修改之前，已經有兩層防護：

| 防護 | 擋住誰 |
|---|---|
| Host 白名單（`parse_request`） | DNS rebinding：攻擊網域解析到 127.0.0.1 時 Host 不符，直接 403 |
| Origin 白名單（非 GET 與 WebSocket） | 惡意網頁跨站 `fetch` / `<form>` POST：瀏覽器一定帶 `Origin: https://evil…`（或 `null`），403 |
| 瀏覽器同源政策（服務不送任何 CORS 標頭） | 惡意網頁讀不到 GET 回應，所以也拿不到令牌 |

所以**惡意網頁**（跨站、DNS rebinding）現在已經碰不到寫入接口，也讀不到令牌。剩下打得到的是**本機上能連 127.0.0.1 的程式**：

- 同一個使用者帳號的其他程式：本來就能直接讀寫 `~/EasyRead`、`config.json`，對它們做 HTTP 層的防護沒有意義。
- **其他 OS 使用者帳號**（多人共用的電腦）、**沙箱 App**（例如 macOS App Store 程式：能連 localhost，但讀不到你的家目錄）、能存取宿主網路的容器或瀏覽器擴充。這一群是真正的威脅模型：它們拿不到檔案，只能走 HTTP。

關鍵事實：在這次修改前後，這群攻擊者**都能用一個不帶憑證的 GET 拿到寫入令牌**（之前在 JSON 裡，之後在 HTML 裡）。因此 (1)(2) 的修法刻意設計成「就算對方有令牌也擋得住」，而不是依賴令牌保密。

## 1. `openai.base_url` 可被改掉，把 API Key 與論文送到任意主機

### 威脅情境
拿得到令牌的程式可以：

1. `POST /api/config` `{"openai": {"base_url": "https://evil/v1"}}`：Key 欄位沿用已存的，下次翻譯就把 `Authorization: Bearer <Key>` 和論文內容送到 evil。
2. `POST /api/chat/models` 加一張 `preset: "deepseek", base_url: "https://evil"` 的「問 AI」卡片：那張卡片會用 DeepSeek 已存的 Key（`chat_models.engine_cfg`）。
3. `POST /api/models/list` `{"base_url": "https://evil", "preset": "deepseek", "api_key": ""}`：**當下立刻**用已存 Key 打 evil 的 `/models`，不必等使用者翻譯。這一條原本審計沒有列出，這次一起修。
4. `base_url` 填 `file:///…`：urllib 也認得 file 協定，可拿來讀本機檔案（只有回應剛好是 JSON 時才會被當成模型清單，影響小，但沒理由允許）。

API Key 是 GET 拿不到的（`config.public` 只露後四位），所以這是對方**從「能讀論文」升級到「偷走付費 Key」**的路徑，是三項裡最實際的風險。

### 修法（`easyread/key_guard.py`，接在 `settings_api.py`、`chat_models.py`、`openai_api.py`）
不禁止自訂 `base_url`（OpenAI 相容服務、中轉站是合法功能），改成**把已存的 Key 綁定到地址**：

- 某服務商（preset）已存的 Key 只會送往兩種來源（`scheme://host:port`）：
  1. 該 preset 內建的官方地址；
  2. `openai.key_origins[preset]`：使用者**在同一個請求裡親手輸入這把 Key 時一起填的地址**。
     翻譯設定是那次請求的 `base_url`；「問 AI」卡片是前端一起送來的 `key_urls[preset]`（輸入 Key 的那張卡片的地址），**不會順帶授權名單上原有的其他卡片**。
  輸入的是**新的** Key 時整組取代、舊授權作廢（例如攻擊者先用他自己的 Key 授權過 evil）；輸入的就是已存的那把 Key 時加進原有授權（設定頁每次儲存都會重送剛輸入的 Key；能輸入這把 Key 的人本來就能授權任何地址）。
- **升級遷移只做一次**：舊設定檔（沒有 `openai.key_origins_v`）載入時，把「當時已有 Key 的 preset」的翻譯 `base_url` 與同 preset 的自訂卡片記進 `key_origins`。讀取時只在記憶體裡算、不改寫檔案；下一次儲存連同 `key_origins_v` 寫回，之後**不再從磁碟上的卡片或 base_url 推導**。磁碟上的設定只會經由儲存改變，所以第一次儲存前算出來的結果就等於升級當下的狀態。
- **存設定時檢查**（不合格整個拒絕、不寫盤）：
  - `/api/config`：頂層欄位改成白名單加型別檢查（`engine`、`auto_translate`、`target`、`obsidian_vault`、`check_updates`、`batch_pages`、`page_cap`、`concurrency`、`claude`、`codex`、`openai`、`chat`），`openai` 底下也是白名單（`key_origins`、`key_origins_v`、`keys` 不能從請求寫入）；**`chat` 和 `/api/chat/models` 走同一套卡片檢查**（第一輪漏了這條路，審查者重現：從 `/api/config` 帶 `chat` 就能加 evil 卡片，連帶讓 `openai.base_url=evil` 被接受）。
  - 新加或改了地址的卡片：已存 Key 必須認可這個地址；沒改的舊卡片不擋儲存（用的時候擋）。
- **送出時再檢查**（防「先埋卡片、後填 Key」）：`chat_models.engine_cfg` 和 `openai_api._headers` 在要附上已存 Key 時呼叫 `key_guard.use_ok`，地址不在授權裡就丟出錯誤「這個介面地址沒有被認可使用已存的 API Key：請在設定裡為它重新輸入一次 API Key」，**不發出請求**。`/api/models/list` 剛輸入的 Key 標記 `_typed_key`，送哪裡由輸入的人決定。
- `base_url` 只接受 `http://` / `https://`：存設定時檢查，`openai_api._base()` / `models()` 實際送出前再檢查一次。

### 取捨
- **沒有強制只用 https**：使用者可能在區網用 `http://192.168.x.x` 自架服務並帶 Key；強制 https 會破壞合法用法。
- **沒有做「改地址時跳確認框」**：確認框是前端的，攻擊者直接打 API 就繞過了。只有「重新輸入 Key」是攻擊者做不到的確認。
- 使用者體驗的代價：
  - 編輯既有自訂卡片的地址時，要在同一個表單重新貼一次 Key。後端錯誤會照常以「保存失敗：…」吐司顯示。
  - 換一把**新** Key 時，同一家服務商其他自訂地址的卡片會失去授權，要在那些卡片裡再輸入一次。
- 前端唯一的改動：`settings-chat.js` 記下 Key 是在哪個地址的卡片輸入的（`chatKeyUrls`），`settings.js` 存名單時一起送 `key_urls`。

### 測試（`tests/test_security_hardening.py::BaseUrlKeyTest`、`TokenTest::test_http_config_patch_with_chat_refused`）
- 只改 base_url（含 `api.deepseek.com.evil.example`、換埠號、不帶 api_key 欄位）→ 拒絕，config.json 一字不變。
- **審查重現 1**：`save_config({"chat": {...evil 卡片}})` 被拒、接著 `openai.base_url=evil` 也被拒；另走真正的 HTTP `/api/config` 重現一次，回 400。
- **審查重現 2（先埋後填）**：先替沒 Key 的智譜埋 evil 卡片 → 使用者在翻譯設定輸入智譜 Key → `engine_cfg(evil)` 與 `_headers` 都丟 EngineError；使用者在自己的代理卡片輸入同一把 Key → 只授權那張卡片，evil 仍被拒。
- 直接寫進磁碟（繞過儲存檢查）的 evil base_url / 卡片：送出時仍被擋；官方地址照常帶 Key。
- 攻擊者用自己的 Key 授權 evil，之後使用者輸入新 Key → evil 授權作廢。
- 同一把 Key 先在卡片 U 輸入、再隨翻譯設定 T 重送 → U、T 都可用。
- 舊設定遷移：載入不改寫檔案；當時有 Key 的 preset 地址被遷移，沒 Key 的不遷移；第一次儲存寫入 `key_origins_v`。
- 白名單：未知頂層欄位、`port`、錯誤型別、`engine: "evil"`、`openai.key_origins_v`、`openai.keys` 都被拒。
- 其他：自訂地址可在重新輸入 Key 後存；`file://` 等被拒；`/api/models/list` 不把已存 Key 送往新地址。

## 2. `/api/library/move` 可把文獻庫搬到任意目錄

### 威脅情境
拿到令牌的其他帳號 / 沙箱程式可以把文獻庫「複製」到 `/tmp/x`、`/Users/Shared/x` 或它自己預先建好的目錄（重啟後新論文都寫到那裡，它讀得到），或用 `use` / `merge` 換成它準備好的文獻庫（內容注入）。實際影響要等重啟才生效，而且同一群攻擊者本來就能用 GET 讀論文，所以這項的**增量風險中等**：主要是「持續外洩」和「換成攻擊者的文獻庫」。

### 修法（`easyread/cloudlib.py::_check_owner`，在 `move()` 裡、`inspect()` 之前）
POSIX 上**擋住屬於他人或他人可寫的目錄**：
- 目標目錄（不存在時取最近一個已存在的上層目錄）必須屬於目前使用者（`st_uid == os.getuid()`），而且群組與其他人都不可寫（沒有 `S_IWGRP`、`S_IWOTH`）。
  - `/tmp/新目錄`、`/Users/Shared/…`（root 所有、sticky 全員可寫）→ 拒絕。
  - 其他帳號的目錄、攻擊者帳號預先建好的目錄、權限 770 / 707 / 777 的目錄 → 拒絕。
- `use` / `merge` 會直接採用目標裡已有的內容：目標裡每個檔案與資料夾（不跟隨符號連結）也都必須屬於目前使用者，而且（符號連結以外）群組與其他人不可寫。屬於自己但他人可寫的子目錄，別人之後仍能放檔案或改內容（整合分支加上，掃描工具回報）。
- 自己家目錄下、網盤同步資料夾（`~/Library/CloudStorage/…`、`~/Dropbox`）照常。

### 取捨與部分修補的理由
- **同一個 uid 的沙箱程式**把目標設成它自己容器內的目錄（例如 `~/Library/Containers/<它>/…`，屬於你、權限也正常）擋不住。要真正擋住，需要「目標必須由使用者在原生選資料夾視窗選出」之類只有人能完成的確認；但 Electron 版在 renderer 選資料夾、瀏覽器版在選不出時讓人手打路徑，伺服器分不出是人選的還是程式送的，改這個會牽動前端流程，不符合「最小修改」，列為殘留風險。
- **會誤擋的合法情況**：FAT/exFAT 外接碟在 macOS 常顯示為 `drwxrwxrwx`，現在會被當成「他人可寫」而拒絕；要放在外接碟，請用 APFS / HFS+ 格式，或在碟上建一個權限 755 的資料夾。
- Windows 沒有 `getuid`，不檢查。

### 測試（`LibraryMoveOwnerTest`）
- 模擬目錄屬於別的帳號（patch `getuid`）→ 拒絕，目標沒被建立，`library_dir` 不變，狀態回到 idle。
- 搬到 `/tmp/easyread-attack-…` → 拒絕。
- 權限 770、707、777 的目錄 → 拒絕。
- `use` 一個裡面有他人擁有檔案的文獻庫（patch `lstat` 模擬）→ 拒絕；全是自己的檔案 → 照常可用。
- `use` 一個裡面有權限 777 / 775 子目錄或 666 檔案的文獻庫 → 拒絕；改回 755 / 644 → 照常可用（整合分支）。
- 搬到自己的目錄 → 照常成功、論文檔案有複製過去。

## 3. 寫入令牌由 GET 的 JSON 回傳

### 威脅情境（誠實評估）
- 惡意網頁：本來就讀不到 JSON（同源政策 + 無 CORS），`<script src=/api/library>` 也會因為 JSON 物件不是合法 JS 而解析失敗。**本來就安全**。
- 本機程式：之前 `curl /api/library` 就能拿到令牌，之後 `curl /` 從 HTML 也拿得到。**對這群攻擊者，這項修改不提供保護。**

所以這項是**縱深防禦**：令牌不再出現在任何 JSON 接口的回應裡（這些回應會被輪詢、被除錯工具和擴充程式攔截紀錄、被貼到 issue 裡；未來若某支 API 不小心加了 CORS，也不會順便洩漏令牌），只剩兩個 HTML 頁面帶它。

### 修法
- `server.py::_page`：`library.html` / `reader.html` 回應時在 `<head>` 注入 `<meta name="easyread-token" content="…">`；`/api/library` 與 `/api/p/{id}/state` 不再有 `token` 欄位。匯出的離線 HTML（`build.py`）不經過 `_page`，不會帶令牌。
- 前端 `common/util.js`：`PR.token` 從 meta 取；新增 `PR.refreshToken()`（重新抓首頁 HTML 解析 meta）；`PR.api` 遇到 `403 bad token` 自動重取令牌、重送一次（服務重啟後令牌會換）。
- `reader/store.js`：`reloadToken()` 改呼叫 `PR.refreshToken()`，載入時不再從 `/state` 取令牌；`library/app.js` 不再從 `/api/library` 取令牌。
- CLI（`cli.py::server_token`）與 Electron（`main.cjs::backendToken`，用於關閉後端）改從首頁 HTML 解析。
- 令牌比對改用 `hmac.compare_digest`。
- 順手修掉一個實測發現的 bug：`do_POST` 令牌不符時沒讀請求體就回 403、連線保持，殘留的請求體會被當成下一個請求而回 **501**。前端自動重送會踩到，所以改成回 403 時關閉連線（`_reject`）。

### 為什麼不用 SameSite cookie
cookie 也要靠某個 GET 回應發下來，本機程式一樣拿得到，效果和 meta 相同，卻要多處理 cookie 屬性和 Electron 的 cookie 行為。真正能擋本機其他帳號的做法見「殘留風險」。

### 測試（`TokenTest`，另更新 `test_hostcheck.py`、`test_presence.py`）
- `/api/library`、`/api/p/{id}/state`、`/api/config`、`/api/jobs` 不含令牌也不含 `"token"` 欄位。
- `/`、`/read/{id}` 含 meta 令牌。
- 不帶令牌、錯誤令牌、少一個字元的令牌 → 403；`server_token()` 取得的令牌 → 200。
- 403 之後同一條 keep-alive 連線送正確令牌 → 200（回歸測試，改回舊行為會失敗）。
- 掃描前端 JS 與 `electron/main.cjs`：沒有任何從 JSON 讀令牌的寫法。

## 4. 整合上游 v1.4.4（分支 `integrate/v1.4.4-secure`）

上游把大部分模組搬進子套件，防護跟著搬到新位置：

| 防護 | 原位置（fix 分支） | 整合分支位置 |
|---|---|---|
| Key 綁定地址 | `easyread/key_guard.py` | 同（頂層，與 `cli_guard.py` 並列），改用上游 `app/api_keys.py` 的 Key 分槽 |
| 設定白名單、chat 檢查、models/list | `easyread/settings_api.py` | `easyread/server/settings_api.py` |
| 一次性遷移、`key_origins_v` | `easyread/config.py` | `easyread/app/config.py` |
| 送出前檢查 | `chat_models.py`、`openai_api.py` | `easyread/chat/chat_models.py`、`easyread/engines/openai_api.py` |
| 搬家目錄檢查 | `easyread/cloudlib.py` | `easyread/library/cloudlib.py` |
| 令牌 meta、403 關連線、hmac | `easyread/server.py` | `easyread/server/server.py` |
| CLI 讀令牌 | `easyread/cli.py` | `easyread/app/cli.py` |

### 上游的 Key 分槽與本加固的關係
上游 v1.4.4 自己也修了一半：自訂地址的 Key 改存在 `keys["url:<地址>"]`，換地址就換槽，舊 Key 不會跟過去。但**官方服務商（preset）的 Key 仍只按 preset 存**，只改 `base_url` 照樣會帶著 DeepSeek / OpenAI 的 Key 走。所以整合後：
- preset 的 Key：仍走 `key_origins` 授權（第 1 節）。
- 自訂地址（preset 為空）的 Key：槽本身就綁定地址，`key_guard` 直接認可「存在這個地址槽裡的 Key」，不再另外記 `key_origins[""]`。
- 一次性遷移時，把舊的無名 Key（`keys[""]`）歸給當時的自訂地址槽，之後不會被別的地址借用。
- 上游新增的 `openai.custom_apis`（自訂接口的名稱、地址、接口類型，不含 Key）加入白名單，並檢查每個地址只能是 http(s)。
- 前端「問 AI」的 Key 改按槽記（`PR.apiKeyId`）；`key_urls` 只對 preset 的 Key 送。

### 新漏洞：上游新增的本機 CLI 引擎繞過 cli_guard
上游新增 CodeBuddy、Grok Build、Antigravity（`agy`）、Cursor 四個 CLI 引擎，`cli_guard` 原本只檢查 claude / codex。重現：`save_config({"codebuddy": {"command": "/bin/sh", ...}})` 被接受，之後翻譯或問 AI 就會執行 `/bin/sh`。

修法（`easyread/cli_guard.py`、`engines/agent_cli.py`、`engines/codebuddy_cli.py`）：
- `command` 只接受該 CLI 的命令名或它的絕對路徑（檔案存在且可執行）：codebuddy → `codebuddy`；grok → `grok`；agy → `agy`；cursor → `agent` / `cursor-agent`（與上游 `agent_cli.SPECS` 一致，測試會對照）。另外可附 `.cmd`、`.exe`。空字串表示按預設名找（設定頁會送空字串）。
- `extra_args`：不確定這些 CLI 哪些參數無害（可能有放開權限、MCP 之類），**保守起見只能是空陣列**。
- 區段只接受 `command`、`model`、`reasoning_effort`、`extra_args`、`timeout`；`model`、`reasoning_effort` 套用和 claude / codex 相同的格式檢查。「問 AI」名單裡這些引擎的卡片也檢查 `model`。
- **起子程序前再檢查一次**：`agent_cli.path`、`codebuddy_cli.path` 遇到不合格的 command 就當作沒找到；`run()` 先呼叫 `engines.guard`。
- 設定白名單納入上游的新欄位：`translation_instructions`、`paper_concurrency`、四個 CLI 區段、`openai.custom_apis`。
- 順帶：`cli_guard.check_command` 的錯誤訊息改成需要時才產生。原本每次都先呼叫 `tr()`，會去查系統語言。

### 上游測試的調整（都是因為設計改變，不是放寬）
- `tests/engines/test_codebuddy_cli.py`：原本斷言 `command: "custom"` 會被執行，改成用 `codebuddy.cmd`，並新增斷言 `custom`、`/bin/sh` 一律回傳 None。
- `tests/web/test_library_loading.cjs`：原本斷言前端採用 `/api/library` JSON 裡的 token，改成斷言**不採用**。
- `tests/desktop/test_desktop.cjs`：假後端改成在 `/` 回傳帶 meta 令牌的 HTML（Electron 關閉後端時從首頁讀令牌）。
- `tests/server/test_presence.py`：`server_token` 改從 `easyread.app.cli` 匯入。

### 整合分支驗證
- pytest：同步分支基準 813 passed → 整合後 **848 passed, 1 skipped**（多出的是本加固的測試）。
- node 測試（`node --test tests/*.cjs tests/*/*.cjs`，排除 `e2e.cjs`）：同步分支 228 / 228 → 整合後 **228 / 228 pass**。
- 變異檢查：
  - `check_patch` 只查 claude / codex → 35 個失敗；名單只驗 claude / codex → 4 個失敗。
  - agent_cli 起程序前不驗 command → 1 個失敗；codebuddy 同樣拿掉 → 1 個失敗。
  - `use` 不檢查子項可寫 → 4 個失敗；白名單漏 `paper_concurrency` → 1 個失敗。
  - 拿掉「新引擎 extra_args 不擋」那一行沒有測試失敗：參數白名單本來就是空的，那一行只是讓錯誤訊息比較清楚。
- 在埠 8799 實跑（暫存資料目錄）：
  - 首頁回 200，含 meta 令牌。
  - 以下 9 個 GET 都不含令牌：`/api/library`、`/api/config`、`/api/prefs`、`/api/jobs`、`/api/trash`、`/api/log`、`/api/version`、`/api/library/location`、`/api/migrate/status`。
  - 照前端 `collect()` 形狀存一次設定（`batch_pages=3`）回 200。
  - 四個新引擎設 `command=/bin/sh` 都回 400；不帶令牌回 403。

## 驗證紀錄

### pytest
- 改動前（main `bc66b79`）：`567 passed, 1 skipped, 701 subtests passed`
- 第一輪後：`586 passed, 1 skipped, 701 subtests passed`
- 第二輪（審查後修正）後：`595 passed, 1 skipped, 710 subtests passed`
- 變異檢查（拿掉一道防護就有新測試失敗）：
  - 第一輪：`may_send` 永遠 True、拿掉 `_check_owner`、令牌放回 JSON、403 不關連線。
  - 第二輪：`save_config` 不檢查 chat（3 失敗）、`use_ok` 永遠放行（2）、每次從磁碟推導授權（2）、新 Key 不作廢舊授權（1）、輸入 Key 不綁定 `key_urls`（3）、不檢查他人可寫（4）、`use` 不檢查內容擁有者（1）、拿掉白名單（1）。

### 第二輪 HTTP 重現（埠 8799、暫存資料目錄）
```
設定 DeepSeek + Key                                         → 200
重現 1：POST /api/config {"chat": {evil 卡片}}               → 400「介面地址改了：…請重新輸入一次 API Key」
重現 1 續：POST /api/config {"openai": {"base_url": evil}}   → 400（同上）
重現 2：先埋智譜 evil 卡片（沒 Key）→ 200；使用者在翻譯設定輸入智譜 Key → 200
        chat_models.engine_cfg(evil) → EngineError「這個介面地址沒有被認可使用已存的 API Key…」，不發請求
重現 3：搬到權限 777 的自有目錄                               → 400「目標資料夾其他使用者也能寫入…」
```

### 實際啟動服務（埠 8799、暫存的 EASYREAD_HOME / 文獻庫，未碰 8765 與真實設定）

```
$ curl -s $U/api/library | grep -c '"token"'          → 0
(a) 不帶令牌寫入  POST /api/prefs                       → {"error": "bad token"} HTTP 403
(a) 錯誤令牌寫入                                        → {"error": "bad token"} HTTP 403
(a) 正確令牌 + Origin: https://evil.example             → {"error": "不允許的請求來源"} HTTP 403
(b) 模擬前端：GET / 取 <meta name="easyread-token">，帶 X-Token 寫入 → HTTP 200
(1) 設定 DeepSeek + 親手輸入 Key                        → HTTP 200
(1) 攻擊：只改 base_url、沿用打碼 Key                   → 「介面地址改了：…請重新輸入一次 API Key」HTTP 400
(1) 攻擊：/api/models/list 指向新地址、用已存 Key       → {"ok": false, …} 未發出請求
(1) 磁碟上的 base_url 仍是 https://api.deepseek.com
(2) 攻擊：搬到 /tmp/easyread-steal                      → 「目標資料夾不屬於目前使用者…：/private/tmp」HTTP 400（目錄未建立）
(2) 攻擊：搬到 /Users/Shared/easyread-steal             → 同上，HTTP 400
(2) 正常：搬到自己的資料夾                              → {"ok": true, …} HTTP 200
```

前端流程另用 Node 載入真正的 `i18n.js` + `util.js`（假 DOM、真 fetch 打 8799）模擬：
`PR.token` 由 meta 取得 ✓；`PR.api` 寫入 ✓；把令牌改成過期值後 `PR.api` 自動重取並成功 ✓。
**未在真實瀏覽器裡點測**（Chrome 擴充未連線；`tests/e2e.cjs` 寫死 Windows 路徑且本機沒有 playwright），建議合併前開一次文獻庫頁、閱讀頁，做一次劃線/筆記、改一次設定。

### 原本讀令牌的地方（全部已改）
| 位置 | 原本 | 現在 |
|---|---|---|
| `web/js/library/app.js` | `PR.token = d.token`（/api/library） | 刪除，用 util.js 從 meta 取的值 |
| `web/js/reader/store.js` 載入 | `PR.token = d.token`（/state） | 刪除 |
| `web/js/reader/store.js` `reloadToken` | `fetch(/state).json().token` | `PR.refreshToken()` |
| `cli.py`（serve、translate 兩處） | `/api/library` 的 `["token"]` | `server_token(url)` |
| `electron/main.cjs` 關閉後端 | `info.token` | `backendToken()` |
| `tests/test_presence.py`、`tests/test_hostcheck.py` | 從 JSON 取／斷言 JSON 有令牌 | 改從 HTML 取／斷言 JSON 沒有令牌 |

## 殘留風險

1. **本機其他帳號與沙箱程式仍能取得令牌，也仍能用 GET 讀所有論文**（`/p/{id}/source.pdf`、`/api/p/{id}/state` 等 GET 都不需要憑證）。根治做法是 Jupyter 式：啟動時產生祕密，只透過啟動器開的網址（或 Electron）交給瀏覽器，伺服器設 HttpOnly SameSite=Strict cookie，GET 也要驗。這會改變書籤與開啟方式，不是最小修改，建議另開議題。
2. **少數 GET 有副作用**，可被跨站 `<img src>` 觸發（不需要令牌）：`/api/update?force=1`（對 GitHub 發請求）、`/api/engines?fresh=1`（重新偵測 CLI）、`/api/p/{id}/state`（更新 last_opened、狀態改為閱讀中）、`/api/p/{id}/export`。目前看來只是小幅擾動，未修。
3. **base_url**：「先埋卡片、後填 Key」第二輪已擋（送出時檢查）。剩下的是：拿到令牌的人仍能**埋**沒 Key 的卡片、或把翻譯地址改成 evil（只要那家還沒存 Key），使用者之後若**就在那張卡片 / 那個地址上**輸入 Key，就等於自己授權了它。前提是使用者沒注意到地址被改。另外沒 Key 的服務（例如自架、免 Key）送出的論文內容本來就不受 Key 綁定保護。
4. **文獻庫搬家**：同 uid 的沙箱程式可指定自己容器內的目錄（見第 2 節）；Windows 未檢查，且 Windows 上 UNC 路徑（`\\host\share`）在 `inspect` 時就會連線，可能洩漏 NTLM 雜湊，未處理；`/api/library/cleanup` 這次沒有深入審查。
5. 前端沒有在真實瀏覽器實測（見上）。
6. 上游 v1.4.4 新增的 `/api/migrate/*`（從 Zotero 搬資料，會讀使用者指定的資料夾）與 `/api/zotero/detect` 這次沒有審查。
