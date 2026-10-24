"""成批匯入的來源授權（2026-10-24 資安加固）。

威脅：別的帳號／沙箱程式能 GET / 拿到寫入令牌，再 POST /api/migrate/start 指定「你自己的」資料夾
（例如 ~/Documents），檔案都屬於你，擁有者檢查擋不住；匯入後再用不需令牌的 GET /p/<id>/source.pdf 讀走。

所以 /api/migrate/scan、/api/migrate/start 不再接受任意路徑字串，只接受這次服務期間「使用者親手選的」路徑：
- 瀏覽器版：/api/library/pick-folder 由後端彈出系統選資料夾視窗，選完回傳一次性 nonce；
- 桌面版：Electron 主程序彈視窗，再用只有它知道的 EASYREAD_DESKTOP_SECRET 向後端換 nonce（/api/pick/grant）；
- 自動偵測到的 Zotero 資料夾：POST /api/zotero/confirm 只能指定「伺服器自己偵測到的第幾個」，不能帶路徑。
nonce 綁定真實路徑、30 分鐘有效，start 用掉就作廢（scan 不用掉，方便先看一眼）。
"""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time

TTL = 30 * 60


def _real(path) -> str:
    try:
        return os.path.realpath(os.path.expanduser(str(path or "")))
    except (OSError, ValueError):
        return ""


class PickGrants:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[str, tuple[str, float]] = {}

    def issue(self, path: str) -> str:
        real = _real(path)
        if not real or not os.path.exists(real):
            return ""
        nonce = secrets.token_urlsafe(18)
        with self.lock:
            now = time.monotonic()
            self.items = {k: v for k, v in self.items.items() if v[1] > now}
            self.items[nonce] = (real, now + TTL)
        return nonce

    def check(self, nonce, path, consume: bool = False) -> bool:
        if not isinstance(nonce, str) or not nonce:
            return False
        real = _real(path)
        with self.lock:
            hit = self.items.get(nonce)
            if not hit or hit[1] < time.monotonic() or not real or not hmac.compare_digest(hit[0], real):
                return False
            if consume:
                del self.items[nonce]
        return True


def of(app) -> PickGrants:
    if not getattr(app, "pick_grants", None):
        app.pick_grants = PickGrants()
    return app.pick_grants


def desktop_secret_ok(app, header) -> bool:
    secret = getattr(app, "desktop_secret", "") or ""
    return bool(secret) and isinstance(header, str) and hmac.compare_digest(header, secret)
