# 本機服務資安加固（2026-10-22）

分支：`fix/security-hardening`（從 main `bc66b79` 開出）。
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

### 修法（`easyread/key_guard.py`，接在 `settings_api.py`）
不禁止自訂 `base_url`（OpenAI 相容服務、中轉站是合法功能），改成**把已存的 Key 綁定到地址**：

- 某服務商（preset）已存的 Key 只會送往這些來源（`scheme://host:port`）：
  1. 該 preset 內建的官方地址；
  2. 使用者**親手輸入這把 Key 時一起填的地址**（記在 `openai.key_origins[preset]`）；
  3. 升級前已存在設定檔裡的地址（翻譯設定那個 preset 的 `base_url`、名單裡同 preset 的卡片），免得舊使用者升級後要重填。
- 要把已存的 Key 用到新地址：**在同一次儲存裡重新輸入一次 Key**。能輸入 Key 的人本來就知道 Key，攻擊者不知道，所以重新輸入本身就是確認。
- 不合格就整個拒絕、不寫盤，錯誤訊息：「介面地址改了：為了不把已存的 API Key 送到新地址，請重新輸入一次 API Key」。
- `/api/models/list` 用已存 Key 時也走同一個檢查；不合格回 `{"ok": false, …}`，**不發出任何請求**。
- `base_url` 只接受 `http://` / `https://`：存設定時檢查，`openai_api._base()` / `models()` 實際送出前再檢查一次。
- `key_origins` 不能由請求直接寫入。
- 切換 preset 時，若舊 preset 有 Key 但還沒記地址，就把當時的地址補記下來，切走再切回不用重填。

### 取捨
- **沒有強制只用 https**：使用者可能在區網用 `http://192.168.x.x` 自架 vLLM / Ollama 並帶 Key；強制 https 會破壞這種合法用法。綁定地址已經擋住「默默換地址」，http 被竊聽是另一個問題，不在這次範圍。
- **沒有做「改地址時跳確認框」**：確認框是前端的，攻擊者直接打 API 就繞過了。只有「重新輸入 Key」是攻擊者做不到的確認。
- 使用者體驗的代價：編輯既有自訂卡片的地址時，要在同一個表單重新貼一次 Key。前端不需改動，後端錯誤會照常以「保存失敗：…」吐司顯示。

### 測試（`tests/test_security_hardening.py::BaseUrlKeyTest`）
- 只改 base_url（含 `api.deepseek.com.evil.example`、換埠號、不帶 api_key 欄位）→ 拒絕，且 config.json 一字不變。
- 重新輸入 Key 的自訂地址 → 可存；之後同地址加打碼 Key → 可存。
- 官方 preset 互換 → 照常可用。
- `file://`、`ftp://`、`javascript:` → 拒絕；`_base()` / `models()` 也拒絕。
- 舊版設定（自訂地址 + Key、沒有 key_origins）→ 原地址照常可存、切走再切回可存、改成 evil 被拒。
- 「問 AI」卡片：evil 地址 + 打碼 Key 被拒；同次重新輸入 Key 則可存；沒有自訂地址的卡片不受影響。
- `/api/models/list`：evil 地址 + 打碼 Key 不呼叫 `openai_api.models`；官方地址用已存 Key；新地址用剛輸入的 Key。

## 2. `/api/library/move` 可把文獻庫搬到任意目錄

### 威脅情境
拿到令牌的其他帳號 / 沙箱程式可以把文獻庫「複製」到 `/tmp/x`、`/Users/Shared/x` 或它自己預先建好的目錄（重啟後新論文都寫到那裡，它讀得到），或用 `use` / `merge` 換成它準備好的文獻庫（內容注入）。實際影響要等重啟才生效，而且同一群攻擊者本來就能用 GET 讀論文，所以這項的**增量風險中等**：主要是「持續外洩」和「換成攻擊者的文獻庫」。

### 修法（`easyread/cloudlib.py::_check_owner`，在 `move()` 裡、`inspect()` 之前）
POSIX 上，目標目錄（不存在時取最近一個已存在的上層目錄）**必須屬於目前使用者**（`st_uid == os.getuid()`）。
- `/tmp/新目錄` → 最近的已存在目錄是 `/private/tmp`（root）→ 拒絕。
- `/Users/Shared/…`（root）、其他帳號的目錄、攻擊者帳號預先建好的目錄 → 拒絕。
- 自己家目錄下、網盤同步資料夾（`~/Library/CloudStorage/…`、`~/Dropbox`）、自己掛載的外接碟 → 照常。

### 取捨與部分修補的理由
- 只修了一部分：**同一個 uid 的沙箱程式**把目標設成它自己容器內的目錄（例如 `~/Library/Containers/<它>/…`，也屬於你）擋不住。要真正擋住，需要「目標必須由使用者在原生選資料夾視窗選出」之類只有人能完成的確認；但 Electron 版是在 renderer 選資料夾、瀏覽器版在選不出時讓人手打路徑，伺服器分不出是人選的還是程式送的，改這個會牽動前端流程，不符合「最小修改」，列為殘留風險。
- 沒有加「上層目錄不可是 world-writable」的檢查：FAT/exFAT 外接碟在 macOS 常顯示為 `drwxrwxrwx`，會誤擋合法用法。
- Windows 沒有 `getuid`，不檢查。

### 測試（`LibraryMoveOwnerTest`）
- 模擬目錄屬於別的帳號（patch `getuid`）→ 拒絕，目標沒被建立，`library_dir` 不變，狀態回到 idle。
- 搬到 `/tmp/easyread-attack-…` → 拒絕。
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

## 驗證紀錄

### pytest
- 改動前（main `bc66b79`）：`567 passed, 1 skipped, 701 subtests passed`
- 改動後：`586 passed, 1 skipped, 701 subtests passed`（新增 19 個測試）
- 變異檢查：把 `may_send` 改成永遠 True → 5 個新測試失敗；拿掉 `_check_owner` → 2 個失敗；令牌放回 JSON → 1 個失敗；403 不關連線 → 1 個失敗。

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
3. **base_url 的預埋攻擊**：攻擊者先替「還沒存 Key 的服務商」加一張 evil 地址的卡片（此時沒 Key 可偷，允許），之後使用者在設定頁替那家服務商輸入 Key 時，同一次儲存會把名單上該服務商的所有自訂地址一併認可。前提是使用者沒注意到名單上多了一張陌生卡片。
4. **文獻庫搬家**：同 uid 的沙箱程式可指定自己容器內的目錄（見第 2 節）；Windows 未檢查，且 Windows 上 UNC 路徑（`\\host\share`）在 `inspect` 時就會連線，可能洩漏 NTLM 雜湊，未處理；`/api/library/cleanup` 這次沒有深入審查。
5. 前端沒有在真實瀏覽器實測（見上）。
