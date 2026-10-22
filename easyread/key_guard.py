"""已存的 API Key 只送往「當初跟它一起存下」的地址（2026-10-22 資安加固）。

威脅：拿得到寫入令牌的人（本機其他程式、其他使用者帳號）可以只改 openai.base_url、
或在「問 AI」名單加一張自訂地址的卡片、或對 /api/models/list 指定任意地址，
而沿用已存的 Key → 下次翻譯／對話／取模型列表就把 Key 和論文內容送到他的主機。

規則：
- base_url 只接受 http:// 或 https://（擋 file:// 等 urllib 也認得的協定）。
- 某服務商（preset）已存的 Key，只會送到這些「源」（scheme://host:port）：
  1. 該 preset 內建的官方地址；
  2. 使用者在同一次儲存裡親手輸入這把 Key 時填的地址（記在 openai.key_origins[preset]）；
  3. 升級前就已存在設定檔裡的地址（翻譯設定那個 preset 的 base_url、名單裡同 preset 的卡片）。
- 要把已存的 Key 用在新地址：重新輸入一次 Key（能輸入 Key 的人本來就知道 Key，攻擊者不知道）。
base_url 本身仍可自由填寫（OpenAI 相容服務是合法功能），只是換地址時不能「默默」沿用舊 Key。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .i18n import tr
from .presets import PRESETS

MASK = "••••"


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


def has_key(cfg: dict, preset: str) -> bool:
    o = cfg.get("openai") or {}
    keys = dict(o.get("keys") or {})
    if o.get("api_key"):
        keys.setdefault(o.get("preset") or "", o["api_key"])
    return bool(keys.get(preset or ""))


def allowed(cfg: dict, preset: str) -> set[str]:
    """這個 preset 已存的 Key 可以送往哪些源（cfg 是目前存在磁碟上的設定）。"""
    preset = preset or ""
    o = cfg.get("openai") or {}
    out = {origin(p["base_url"]) for p in PRESETS if p["id"] == preset}
    recorded = (o.get("key_origins") or {}).get(preset)
    if isinstance(recorded, list):
        out.update(str(x) for x in recorded)
    if (o.get("preset") or "") == preset:  # 升級前存的翻譯設定
        out.add(origin(o.get("base_url")))
    for m in (cfg.get("chat") or {}).get("models") or []:  # 已存的「問 AI」卡片
        if isinstance(m, dict) and m.get("engine") == "openai" and (m.get("preset") or "") == preset and m.get("base_url"):
            out.add(origin(m["base_url"]))
    out.discard("")
    return out


def may_send(cfg: dict, preset: str, url) -> bool:
    """已存的 Key 可以送往 url 嗎？沒存 Key、或地址空著（之後會用官方地址）都算可以。"""
    if not str(url or "").strip() or not has_key(cfg, preset):
        return True
    return origin(url) in allowed(cfg, preset)


def refuse() -> ValueError:
    return ValueError(tr("接口地址改了：为了不把已存的 API Key 发到新地址，请重新输入一次 API Key"))


def remember(key_origins: dict, preset: str, urls) -> dict:
    """使用者親手輸入了這個 preset 的 Key：記下這次一起送來的地址（取代舊紀錄；換 Key 等於重新授權）。"""
    out = dict(key_origins or {})
    found = sorted({origin(u) for u in urls} - {""})
    if found:
        out[preset or ""] = found
    return out
