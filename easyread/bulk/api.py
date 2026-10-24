"""成批导入的接口：找 Zotero 数据目录；看一眼有多少、开始 / 停止、查进度（Zotero 和文件夹共用）。"""
from __future__ import annotations

from ..app.i18n import tr
from ..zotero import locate
from .runner import Migration


def _mig(app) -> Migration:
    if not getattr(app, "bulk", None):
        app.bulk = Migration(app)
    return app.bulk


def get(app, path: str):
    if path == "/api/zotero/detect":
        return {"candidates": locate.candidates()}
    if path == "/api/migrate/status":
        return _mig(app).status
    return None


def _granted(app, body: dict, where: str, consume: bool) -> None:
    """來源路徑必須是這次服務期間使用者親手選的（選資料夾視窗或確認自動偵測的 Zotero），見 server/pick_grants.py。"""
    from ..server import pick_grants
    if not pick_grants.of(app).check(body.get("nonce"), where, consume=consume):
        raise ValueError(tr("请用“选择文件夹”重新选一次要导入的文件夹（只接受这次亲手选的文件夹）"))


def post(app, path: str, body: dict):
    source, where, base = str(body.get("source") or "zotero"), str(body.get("path") or ""), str(body.get("base") or "")
    if path == "/api/zotero/confirm":  # 只能確認伺服器自己偵測到的第幾個，不能帶路徑
        found = locate.candidates()
        i = body.get("index")
        if type(i) is not int or not 0 <= i < len(found):
            raise ValueError(tr("没有这个 Zotero 文件夹"))
        from ..server import pick_grants
        return {"path": found[i]["path"], "nonce": pick_grants.of(app).issue(found[i]["path"])}
    if path == "/api/migrate/scan":
        _granted(app, body, where, consume=False)
        return _mig(app).scan(source, where, base)
    if path == "/api/migrate/start":
        _granted(app, body, where, consume=True)
        return _mig(app).start(source, where, base, with_tags=body.get("tags", True) is not False,
                               fetch=body.get("fetch") is True, link=body.get("link") is True)
    if path == "/api/migrate/stop":
        return _mig(app).stop()
    return None


GET = {"/api/zotero/detect", "/api/migrate/status"}
POST = {"/api/migrate/scan", "/api/migrate/start", "/api/migrate/stop", "/api/zotero/confirm"}
