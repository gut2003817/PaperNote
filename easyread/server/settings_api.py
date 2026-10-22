"""设置页的保存类接口（POST）。server.py 按路径转过来，每个函数收请求体、返回要回给页面的 JSON。"""
from __future__ import annotations

from .. import cli_guard, key_guard, obsidian_vault
from ..chat import chat_models
from ..app import config
from ..app.api_keys import resolve, saved_keys
from ..engines import engines, openai_api
from ..translate import langs, instructions
from ..app.i18n import tr


# /api/config 接受的頂層欄位與型別（白名單）。chat 走和 /api/chat/models 同一套 Key 地址檢查。
# None = 型別與範圍在 save_config 裡另有檢查與提示。每個本機 CLI 引擎（engines.CLI_ENGINES）一個 dict 區段，交給 cli_guard。
_FIELDS = {"engine": str, "auto_translate": bool, "target": str, "obsidian_vault": str, "check_updates": bool,
           "batch_pages": int, "page_cap": None, "concurrency": int, "paper_concurrency": None, "translation_instructions": None,
           "openai": dict, "chat": dict, **{e: dict for e in engines.CLI_ENGINES}}
_ENGINES = (*engines.CLI_ENGINES, "openai", "none")
_OPENAI_FIELDS = {"preset", "base_url", "api", "model", "api_key", "vision", "timeout", "reasoning_effort", "service_tier", "custom_apis"}


def _check_fields(patch: dict) -> None:
    if not isinstance(patch, dict):
        raise ValueError(tr("设置格式不对"))
    for k, v in patch.items():
        t = _FIELDS.get(k)
        if k not in _FIELDS:
            raise ValueError(tr("不认识的设置项：{key}", key=str(k)[:40]))
        if t is not None and type(v) is not t:  # bool 不当 int；page_cap 在下面有自己的检查与提示
            raise ValueError(tr("设置项 {key} 的格式不对", key=k))
    if "engine" in patch and patch["engine"] not in _ENGINES:
        raise ValueError(tr("设置项 {key} 的格式不对", key="engine"))
    for k in ("batch_pages", "concurrency"):
        if k in patch and patch[k] < 0:
            raise ValueError(tr("设置项 {key} 的格式不对", key=k))
    if "openai" in patch:
        extra = set(patch["openai"]) - _OPENAI_FIELDS
        if extra:
            raise ValueError(tr("不认识的设置项：{key}", key="openai." + sorted(extra)[0][:40]))
        apis = patch["openai"].get("custom_apis")
        if apis is not None:  # 自定义接口只存名称、地址、接口类型；Key 仍在服务端按地址分槽存
            if not isinstance(apis, list) or not all(isinstance(a, dict) and set(a) <= {"name", "base_url", "api"}
                                                     and all(isinstance(v, str) for v in a.values()) for a in apis):
                raise ValueError(tr("设置项 {key} 的格式不对", key="openai.custom_apis"))
            for a in apis:
                key_guard.check_url(a.get("base_url"))


def save_config(patch: dict) -> dict:
    if isinstance(patch, dict):
        patch.pop("library_dir", None)
    _check_fields(patch)
    if "translation_instructions" in patch:
        patch["translation_instructions"] = instructions.validate(patch["translation_instructions"])
    cli_guard.check_patch(patch)  # command / extra_args 等会进子进程的值：一处不合法整个拒绝，不写盘
    if "page_cap" in patch and (type(patch["page_cap"]) is not int or patch["page_cap"] < 0):
        raise ValueError(tr("页数确认上限必须是非负整数"))
    if "paper_concurrency" in patch and (type(patch["paper_concurrency"]) is not int
                                         or not 1 <= patch["paper_concurrency"] <= 4):
        raise ValueError(tr("同时翻译的论文数必须是 1 到 4 的整数"))
    if "target" in patch:
        patch["target"] = langs.valid(patch["target"])
    if "obsidian_vault" in patch:  # 非空才验；不合格抛错，整个 patch 不写盘
        v = patch["obsidian_vault"]
        if not isinstance(v, str):
            raise ValueError(tr("请输入完整的文件夹路径"))
        patch["obsidian_vault"] = v.strip()
        if patch["obsidian_vault"]:
            obsidian_vault.check_vault(patch["obsidian_vault"])
    cur = config.load()
    if "chat" in patch:  # 和 /api/chat/models 同一套检查（自定义地址的卡片不能沿用已存的 Key）
        chat, _ = _chat_patch(patch["chat"], cur, {}, {})
        patch["chat"] = chat
    if "openai" in patch:
        patch["openai"] = _guard_openai(patch["openai"], cur)
    return {"config": config.public(config.save(patch))}


def _guard_openai(o: dict, cur: dict) -> dict:
    """改接口地址時不能默默沿用已存的 Key（見 key_guard.py）。不合格整個拒絕，不寫盤。"""
    co = cur["openai"]
    key_guard.check_url(o.get("base_url"))
    preset = o.get("preset", co.get("preset")) or ""
    url = o.get("base_url", co.get("base_url"))
    origins = dict(co.get("key_origins") or {})
    if key_guard.fresh_key(o.get("api_key")):
        origins = key_guard.entered(cur, origins, preset, o["api_key"], [url])  # 只認這個請求裡一起填的地址
    elif not key_guard.may_send(cur, preset, url):
        raise key_guard.refuse()
    out = config.with_key(o)
    out["key_origins"] = origins
    return out


def _chat_patch(body: dict, cur: dict, fresh: dict, key_urls: dict) -> tuple[dict, dict]:
    """名单的 patch + 新的 key_origins。fresh：这次请求里亲手输入的 Key {服务商: Key}；key_urls：那把 Key 是在哪个地址的卡片里输入的。"""
    if not isinstance(body, dict) or set(body) - {"models", "default"}:
        raise ValueError(tr("设置格式不对"))
    patch = {}
    origins = dict(cur["openai"].get("key_origins") or {})
    for preset, key in {k: v for k, v in fresh.items() if not k.startswith("url:")}.items():  # 只授权同一个请求里它所在卡片的地址；不会顺带授权名单上原有的其他卡片
        url = key_urls.get(preset) if isinstance(key_urls, dict) else None
        origins = key_guard.entered(cur, origins, preset, key, [url] if isinstance(url, str) else [])
    if "models" in body:
        if not isinstance(body["models"], list) or not all(isinstance(m, dict) for m in body["models"]):
            raise ValueError(tr("设置格式不对"))
        patch["models"] = chat_models.sanitize(body["models"])
        saved = {(m.get("preset") or "", m.get("base_url") or "") for m in (cur.get("chat") or {}).get("models") or [] if isinstance(m, dict)}
        after = {**cur, "openai": {**cur["openai"], "key_origins": origins}}
        for m in patch["models"]:
            if m["engine"] != "openai" or not m.get("base_url"):
                continue
            key_guard.check_url(m["base_url"])
            if m["preset"] in fresh and not key_guard.authorized(m["preset"], origins, m["base_url"]) and (m["preset"], m["base_url"]) not in saved:
                raise key_guard.refuse()
            # 新加或改了地址的卡片：已存的 Key 必须认可这个地址；没改的旧卡片不挡保存，用的时候再挡（chat_models.engine_cfg）
            if m["preset"] not in fresh and (m["preset"], m["base_url"]) not in saved and not key_guard.may_send(after, m["preset"], m["base_url"]):
                raise key_guard.refuse()
    if "default" in body:
        if not isinstance(body["default"], str):
            raise ValueError(tr("设置格式不对"))
        if body["default"]:
            patch["default"] = body["default"]
    return patch, origins


def save_chat_models(body: dict) -> dict:
    """保存“问 AI”的名单和默认模型；或面板里只改默认。"""
    cur = config.load()
    keys_in = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    fresh = {str(k): str(v) for k, v in keys_in.items() if key_guard.fresh_key(v)}
    patch, origins = _chat_patch({k: body[k] for k in ("models", "default") if k in body}, cur, fresh, body.get("key_urls") or {})
    full = {"chat": patch}
    keys = saved_keys(cur["openai"])
    keys.update({str(k): str(v).strip() for k, v in keys_in.items() if key_guard.fresh_key(v)})  # 和翻译那边共用；自定义地址按 url:<地址> 分槽
    full["openai"] = {"keys": keys, "key_origins": origins}
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
    o = {"base_url": body.get("base_url"), "api_key": key, "_typed_key": True}  # 刚输入的 Key：送哪里由输入的人决定
    if not key or key.startswith("••••"):
        cfg, preset = config.load(), str(body.get("preset") or "")
        if not key_guard.may_send(cfg, preset, body.get("base_url")):  # 已存的 Key 不送往没认可过的地址
            return {"ok": False, "message": str(key_guard.refuse())}
        o = {"base_url": body.get("base_url"), "preset": preset, "key_origins": cfg["openai"].get("key_origins") or {},
             "keys": saved_keys(cfg["openai"]), "api_key": resolve(cfg["openai"], preset, str(body.get("base_url") or ""))}
    try:
        return {"ok": True, "models": openai_api.models(o)}
    except engines.EngineError as e:
        return {"ok": False, "message": str(e)[:300]}


POST = {"/api/config": save_config, "/api/chat/models": save_chat_models,
        "/api/config/test": test_engine, "/api/models/list": list_models}
