"""设置页的保存类接口（POST）。server.py 按路径转过来，每个函数收请求体、返回要回给页面的 JSON。"""
from __future__ import annotations

from . import chat_models, cli_guard, config, engines, key_guard, langs, obsidian_vault, openai_api
from .i18n import tr


def save_config(patch: dict) -> dict:
    patch.pop("library_dir", None)
    cli_guard.check_patch(patch)  # command / extra_args 等会进子进程的值：一处不合法整个拒绝，不写盘
    if "page_cap" in patch and (type(patch["page_cap"]) is not int or patch["page_cap"] < 0):
        raise ValueError(tr("页数确认上限必须是非负整数"))
    if "target" in patch:
        patch["target"] = langs.valid(patch["target"])
    if "obsidian_vault" in patch:  # 非空才验；不合格抛错，整个 patch 不写盘
        v = patch["obsidian_vault"]
        if not isinstance(v, str):
            raise ValueError(tr("请输入完整的文件夹路径"))
        patch["obsidian_vault"] = v.strip()
        if patch["obsidian_vault"]:
            obsidian_vault.check_vault(patch["obsidian_vault"])
    if isinstance(patch.get("openai"), dict):
        patch["openai"] = _guard_openai(patch["openai"])
    return {"config": config.public(config.save(patch))}


def _guard_openai(o: dict) -> dict:
    """改接口地址時不能默默沿用已存的 Key（見 key_guard.py）。不合格整個拒絕，不寫盤。"""
    cur = config.load()
    co = cur["openai"]
    if "key_origins" in o:
        raise ValueError(tr("不能直接修改 key_origins"))
    key_guard.check_url(o.get("base_url"))
    preset = o.get("preset", co.get("preset")) or ""
    url = o.get("base_url", co.get("base_url"))
    origins = dict(co.get("key_origins") or {})
    old = co.get("preset") or ""
    if old not in origins and key_guard.has_key(cur, old) and key_guard.origin(co.get("base_url")):
        origins[old] = [key_guard.origin(co.get("base_url"))]  # 舊設定沒記地址：補記，切走再切回不用重填 Key
    if key_guard.fresh_key(o.get("api_key")):
        origins = key_guard.remember(origins, preset, [url])
    elif not key_guard.may_send(cur, preset, url):
        raise key_guard.refuse()
    out = config.with_key(o)
    out["key_origins"] = origins
    return out


def save_chat_models(body: dict) -> dict:
    """保存“问 AI”的名单和默认模型；或面板里只改默认。"""
    patch = {}
    cur = config.load()
    fresh = {str(k) for k, v in body["keys"].items() if key_guard.fresh_key(v)} if isinstance(body.get("keys"), dict) else set()
    origins = dict(cur["openai"].get("key_origins") or {})
    if "models" in body:
        patch["models"] = chat_models.sanitize(body["models"])
        # 自訂地址的卡片：已存的 Key 只能送往原本認可的地址；新地址要在這次一起重新輸入那家的 Key（見 key_guard.py）
        new_urls: dict[str, list] = {}
        for m in patch["models"]:
            if m["engine"] != "openai" or not m.get("base_url"):
                continue
            key_guard.check_url(m["base_url"])
            if m["preset"] in fresh:
                new_urls.setdefault(m["preset"], []).append(m["base_url"])
            elif not key_guard.may_send(cur, m["preset"], m["base_url"]):
                raise key_guard.refuse()
        for preset, urls in new_urls.items():
            origins = key_guard.remember(origins, preset, urls + list(origins.get(preset) or []))
    if body.get("default"):
        patch["default"] = str(body["default"])
    full = {"chat": patch}
    if isinstance(body.get("keys"), dict):  # 设置里给某家 API 填的 Key，和翻译那边共用
        keys = dict(cur["openai"].get("keys") or {})
        keys.update({str(k): str(v).strip() for k, v in body["keys"].items() if v and not str(v).startswith("••••")})
        full["openai"] = {"keys": keys, "key_origins": origins}
    elif origins != (cur["openai"].get("key_origins") or {}):
        full["openai"] = {"key_origins": origins}
    config.save(full)
    return chat_models.listing(config.load())


def test_engine(body: dict) -> dict:
    cfg = config.load()
    if body.get("engine"):
        cfg["engine"] = body["engine"]
    return engines.test(cfg)


def list_models(body: dict) -> dict:
    """设置页“获取模型列表”：{base_url, preset, api_key}；Key 留空或打码时用这家已存的。"""
    key = str(body.get("api_key") or "").strip()
    try:
        key_guard.check_url(body.get("base_url"))
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    if not key or key.startswith("••••"):
        cfg, preset = config.load(), str(body.get("preset") or "")
        if not key_guard.may_send(cfg, preset, body.get("base_url")):  # 已存的 Key 不送往没认可过的地址
            return {"ok": False, "message": str(key_guard.refuse())}
        key = (cfg["openai"].get("keys") or {}).get(preset, "")
    try:
        return {"ok": True, "models": openai_api.models({"base_url": body.get("base_url"), "api_key": key})}
    except engines.EngineError as e:
        return {"ok": False, "message": str(e)[:300]}


POST = {"/api/config": save_config, "/api/chat/models": save_chat_models,
        "/api/config/test": test_engine, "/api/models/list": list_models}
