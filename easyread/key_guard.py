"""已存的 API Key 只送往「使用者輸入這把 Key 時一起填的地址」或該服務商官方地址（2026-10-22 資安加固）。

威脅：拿得到寫入令牌的人（本機其他程式、其他使用者帳號）可以只改 openai.base_url、
在「問 AI」名單加一張自訂地址的卡片、或對 /api/models/list 指定任意地址，
沿用已存的 Key → 把 Key 和論文內容送到他的主機。

規則：
- base_url 只接受 http:// 或 https://。
- 某服務商（preset）已存的 Key 只會送往：
  1. 該 preset 內建的官方地址；
  2. openai.key_origins[preset]：使用者在同一個請求裡親手輸入這把 Key 時一起填的地址
     （每次輸入新 Key 都會整組取代，舊授權作廢）。
  升級前的設定只在第一次載入時遷移一次（openai.key_origins_v），之後不再從磁碟上的卡片或 base_url 推導。
- 存設定時檢查（不合格整個拒絕），實際送出時（chat_models.engine_cfg、openai_api._headers）再檢查一次，
  所以就算有人先埋一張卡片、之後使用者才輸入 Key，那張卡片也拿不到 Key。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .app.api_keys import key_id, saved_keys
from .app.i18n import tr
from .engines.presets import PRESETS

MASK = "••••"
FLAG = "key_origins_v"  # 已做過一次性遷移


def origin(url) -> str:
    """http(s) 網址 → "scheme://host:port"（小寫、補預設埠）；不是 http(s) 或沒有主機回空字串。"""
    try:
        u = urlsplit(str(url or "").strip())
        port = u.port
    except ValueError:
        return ""
    scheme = u.scheme.lower()
    if scheme not in ("http", "https") or not u.hostname:
        return ""
    return f"{scheme}://{u.hostname.lower()}:{port or (443 if scheme == 'https' else 80)}"


def check_url(url) -> None:
    """非空的接口地址必須是 http(s)。"""
    if str(url or "").strip() and not origin(url):
        raise ValueError(tr("接口地址必须以 http:// 或 https:// 开头"))


def fresh_key(value) -> bool:
    """頁面送來的是使用者新輸入的 Key（不是空的、也不是打碼的舊 Key）。"""
    return bool(value) and isinstance(value, str) and bool(value.strip()) and not value.startswith(MASK)


def stored_key(cfg: dict, preset: str, url="") -> str:
    """這個 preset（自訂地址時是 url:<地址> 槽，見 app/api_keys.py）已存的 Key。"""
    return str(saved_keys(cfg.get("openai") or {}).get(key_id(preset or "", str(url or ""))) or "")


def has_key(cfg: dict, preset: str, url="") -> bool:
    return bool(stored_key(cfg, preset, url))


def official(preset: str) -> set[str]:
    return {origin(p["base_url"]) for p in PRESETS if p["id"] == (preset or "")} - {""}


def authorized(preset: str, key_origins, url) -> bool:
    """這個 preset 的 Key 可以送往 url 嗎（只看官方地址與 key_origins，不看磁碟上的其他設定）。"""
    o = origin(url)
    if not o:
        return False
    recorded = (key_origins or {}).get(preset or "") if isinstance(key_origins, dict) else None
    return o in official(preset) or (isinstance(recorded, list) and o in recorded)


def allowed(cfg: dict, preset: str) -> set[str]:
    rec = ((cfg.get("openai") or {}).get("key_origins") or {}).get(preset or "")
    return official(preset) | ({str(x) for x in rec} if isinstance(rec, list) else set())


def may_send(cfg: dict, preset: str, url) -> bool:
    """存設定時用：已存的 Key 可以配上 url 嗎？沒存 Key、或地址空著（之後會用官方地址）都算可以。"""
    if not str(url or "").strip() or not has_key(cfg, preset, url):
        return True
    if not preset:  # 自訂地址的 Key 存在 url:<地址> 槽（上游 api_keys），本來就只屬於這個地址
        return True
    return authorized(preset, (cfg.get("openai") or {}).get("key_origins"), url)


def use_ok(o: dict) -> bool:
    """實際送出時用：o 是要交給 openai_api 的設定。帶著已存 Key（不是剛輸入的）就必須是認可的地址。"""
    if not o.get("api_key") or o.get("_typed_key"):
        return True
    preset, url = o.get("preset") or "", str(o.get("base_url") or "")
    keys = o.get("keys") if isinstance(o.get("keys"), dict) else {}
    if not preset and url.strip() and keys.get(key_id("", url)) == o["api_key"]:
        return True  # 自訂地址：這把 Key 就是存在這個地址的槽裡
    return authorized(preset, o.get("key_origins"), url)


def migrate(raw: dict) -> dict:
    """升級前的設定只遷移一次：當時已有 Key 的 preset，把翻譯設定的 base_url 與名單上同 preset 的自訂卡片記為已授權。"""
    o = raw.get("openai") if isinstance(raw.get("openai"), dict) else {}
    origins = dict(o.get("key_origins") or {}) if isinstance(o.get("key_origins"), dict) else {}
    cand = [(o.get("preset") or "", o.get("base_url"))]
    chat = raw.get("chat") if isinstance(raw.get("chat"), dict) else {}
    for m in chat.get("models") or []:
        if isinstance(m, dict) and m.get("engine") == "openai" and m.get("base_url"):
            cand.append((m.get("preset") or "", m["base_url"]))
    for preset, url in cand:
        og = origin(url)
        if preset and og and og not in official(preset) and has_key(raw, preset):  # 自訂地址的 Key 本來就按地址分槽
            origins.setdefault(preset, [])
            if og not in origins[preset]:
                origins[preset].append(og)
    # 舊的無名 Key（keys[""]）歸給當時的自訂地址槽，之後不會被別的地址借用（app/api_keys.saved_keys）
    keys = saved_keys(o) if (o.get("keys") or o.get("api_key")) else {}
    out = {**o, "key_origins": origins, FLAG: 1}
    if keys:
        out["keys"] = keys
    return {**raw, "openai": out}


def refuse() -> ValueError:
    return ValueError(tr("接口地址改了：为了不把已存的 API Key 发到新地址，请重新输入一次 API Key"))


def use_refused_message() -> str:
    return tr("这个接口地址没有被认可使用已存的 API Key：请在设置里为它重新输入一次 API Key")


def entered(cfg: dict, key_origins: dict, preset: str, key: str, urls) -> dict:
    """請求裡親手輸入了 preset 的 Key（key）：授權同一個請求裡的地址 urls。
    輸入的就是已存的那把 Key → 加到原有授權（能輸入它的人本來就能授權任何地址；設定頁會在每次儲存時重送剛輸入的 Key）；
    是新 Key → 整組取代，舊授權作廢（例如攻擊者先用他自己的 Key 授權過 evil）。"""
    same = key.strip() == stored_key(cfg, preset)
    old = list((key_origins or {}).get(preset or "") or []) if same else []
    return remember(key_origins, preset, list(urls) + old)


def remember(key_origins: dict, preset: str, urls) -> dict:
    """使用者親手輸入了這個 preset 的 Key：只記下同一個請求裡一起送來的地址，整組取代舊紀錄（換 Key 等於重新授權）。"""
    out = dict(key_origins or {})
    out[preset or ""] = sorted({origin(u) for u in urls} - {""} - official(preset))
    return out
