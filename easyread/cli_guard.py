"""本机 CLI（claude / codex）相关配置的校验：这些值最后会变成子进程的可执行文件和命令行参数。

威胁：POST /api/config 只要带着令牌就能改配置，而 claude.command、codex.command 是要执行的程序，
claude.extra_args、codex.extra_args 是追加到命令行的参数——都等于“让服务器运行任意程序”。
extra_args 本身也是执行载体：claude 的 --settings（hooks 里能写 shell 命令）、--mcp-config（启动任意 MCP 子进程）、
--plugin-dir / --agents、--dangerously-skip-permissions / --permission-mode / --allowedTools（放开工具权限），
codex 的 -c key=value（能改 sandbox、shell、mcp_servers）、--sandbox danger-full-access、
--dangerously-bypass-approvals-and-sandbox、--add-dir 等。所以 command 只认“看起来就是该 CLI”的值，
extra_args 用白名单：只放行调模型 / 推理强度 / 预算这类良性参数，其余一律拒绝。

只在保存路径（settings_api）和真正起子进程之前（engines、chat）调用；读取配置（config.load）时不校验、不改写。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .i18n import tr

NAMES = {"claude": "claude", "codex": "codex"}
_EXTS = ("", ".cmd", ".exe")
# shell 元字符、引号、通配符、环境变量展开（%）、控制字符（含换行）。反斜杠只在 Windows 路径里允许。
_BAD = re.compile(r"[;|&$`<>()\"'*?%!{}\x00-\x1f\x7f]")
_MAX_COMMAND = 1024
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-\[\]]{0,119}$")  # 不能以 - 开头：免得被当成参数
_WORD = re.compile(r"^[a-z]{1,16}$")
_NUMBER = re.compile(r"^[0-9]{1,4}(\.[0-9]{1,4})?$")
_EFFORT = {"low", "medium", "high", "xhigh", "max"}
_CODEX_CONFIG = re.compile(r'^(model_reasoning_effort|model_reasoning_summary|model_verbosity|service_tier)=("?)[a-z]{2,16}\2$')


def _show(v) -> str:
    s = v if isinstance(v, str) else repr(v)
    s = s.replace("\n", "\\n").replace("\r", "\\r")
    return s if len(s) <= 60 else s[:60] + "…"


def _allowed_names(name: str) -> str:
    return "/".join(NAMES[name] + e for e in _EXTS)


def check_command(name: str, value, field: str | None = None) -> str:
    """name：claude 或 codex。合格返回原值，否则抛 ValueError。
    合格 = 裸命令名（claude / claude.cmd / claude.exe），或绝对路径：文件名是这几个之一、文件存在且可执行。
    符号链接不追到目标（官方安装器就是把 claude 链到版本目录下的文件），只看路径本身的文件名。"""
    field = field or f"{name}.command"
    bad = ValueError(tr("{field} 只能填命令名 {names}，或这个命令的绝对路径（文件必须存在且可执行），不能带参数、特殊符号或相对路径：{value}", field=field, names=_allowed_names(name), value=_show(value)))
    if type(value) is not str or not value or len(value) > _MAX_COMMAND:
        raise bad
    stem = NAMES[name]
    if "/" not in value and "\\" not in value:
        if value.lower() in {stem + e for e in _EXTS}:  # 裸名：必须整个就是名字，带空格、参数、点号前缀都不行
            return value
        raise bad
    if not os.path.isabs(value):  # ./claude、../../bin/sh、~/bin/claude 都在这里被挡
        raise bad
    if _BAD.search(value) or (os.name != "nt" and "\\" in value) or ".." in Path(value).parts:
        raise bad
    base = re.split(r"[\\/]", value)[-1] if os.name == "nt" else os.path.basename(value)
    if base.lower() not in {stem + e for e in _EXTS}:
        raise bad
    if not os.path.isfile(value) or not os.access(value, os.X_OK):
        raise bad
    return value


def check_model(value, field: str) -> str:
    if type(value) is not str or (value and not MODEL_RE.fullmatch(value)):
        raise ValueError(tr("{field} 的值不合法（只能含字母、数字和 . _ : / - [ ]，不能以 - 开头，最长 120 字）：{value}", field=field, value=_show(value)))
    return value


def check_word(value, field: str) -> str:
    """reasoning_effort、service_tier：空，或几个小写字母。"""
    if type(value) is not str or (value and not _WORD.fullmatch(value)):
        raise ValueError(tr("{field} 的值不合法（只能是几个小写字母，例如 low、high）：{value}", field=field, value=_show(value)))
    return value


def _v_model(v):
    return bool(MODEL_RE.fullmatch(v))


def _v_effort(v):
    return v in _EFFORT


def _v_budget(v):
    return bool(_NUMBER.fullmatch(v))


def _v_codex_config(v):
    return bool(_CODEX_CONFIG.fullmatch(v))


# 放行的参数 → 值的校验。写成“参数 值”两个独立元素；不收 --参数=值 写法，也不收单独的值（会被当成提示词或子命令）。
ALLOWED_ARGS = {
    "claude": {"--model": _v_model, "--fallback-model": _v_model, "--effort": _v_effort, "--max-budget-usd": _v_budget},
    "codex": {"-m": _v_model, "--model": _v_model, "-c": _v_codex_config, "--config": _v_codex_config},
}


def check_extra_args(name: str, value, field: str | None = None) -> list:
    field = field or f"{name}.extra_args"
    table = ALLOWED_ARGS[name]
    allowed = "、".join(table)  # i18n-ok 参数名列表
    if type(value) is not list:
        raise ValueError(tr("{field} 必须是数组（例如 [\"--model\", \"sonnet\"] 的形式），不能是 {kind}", field=field, kind=type(value).__name__))
    for tok in value:
        if type(tok) is not str:
            raise ValueError(tr("{field} 的每一项都必须是字符串：{value}", field=field, value=_show(tok)))
    i = 0
    while i < len(value):
        tok = value[i]
        flag = tok.split("=", 1)[0]
        if flag in table and "=" in tok:
            raise ValueError(tr("{field} 要把参数和值分成两项写，不支持 {flag}=值 的写法：{value}", field=field, flag=flag, value=_show(tok)))
        if tok not in table:
            if tok.startswith("-"):
                raise ValueError(tr("{field} 不允许使用参数 {flag}（可用的参数只有：{allowed}）", field=field, flag=_show(flag), allowed=allowed))
            raise ValueError(tr("{field} 里的 {value} 不是“参数 值”的形式（可用的参数只有：{allowed}）", field=field, value=_show(tok), allowed=allowed))
        if i + 1 >= len(value) or type(value[i + 1]) is not str or not table[tok](value[i + 1]):
            got = value[i + 1] if i + 1 < len(value) else ""
            raise ValueError(tr("{field} 里参数 {flag} 的值不合法：{value}", field=field, flag=tok, value=_show(got)))
        i += 2
    return value


_SECTION_KEYS = {"claude": {"command", "model", "reasoning_effort", "extra_args", "timeout", "lean"},
                 "codex": {"command", "model", "reasoning_effort", "service_tier", "extra_args", "timeout", "lean"}}


def check_section(name: str, sec, *, save: bool = True) -> None:
    """校验 claude / codex 这一节里会进子进程的值。save=True（保存路径）：类型和未知项也查；
    save=False（起子进程之前）：只查 command、extra_args、model、reasoning_effort、service_tier，没填的跳过。"""
    field = name
    if not isinstance(sec, dict):
        raise ValueError(tr("{field} 必须是对象", field=field))
    if save:
        extra = sorted(set(sec) - _SECTION_KEYS[name])
        if extra:
            raise ValueError(tr("{field} 里没有这个设置项：{key}", field=field, key=_show(extra[0])))
    for key, val in sec.items():
        if key == "command":
            if save or val:
                check_command(name, val, f"{name}.command")
        elif key == "extra_args":
            if save or val:
                check_extra_args(name, val, f"{name}.extra_args")
        elif key == "model":
            if save or val:
                check_model(val, f"{name}.model")
        elif key in ("reasoning_effort", "service_tier"):
            if save or val:
                check_word(val, f"{name}.{key}")
        elif key == "timeout" and save:
            if type(val) is not int or not 1 <= val <= 86400:
                raise ValueError(tr("{field} 必须是 1 到 86400 的整数（秒）", field=f"{name}.timeout"))
        elif key == "lean" and save:
            if type(val) is not bool:
                raise ValueError(tr("{field} 必须是 true 或 false", field=f"{name}.lean"))


def check_chat_models(items) -> None:
    """“问 AI”名单里走本机 CLI 的项：model、reasoning_effort、service_tier 会变成命令行参数。"""
    if not isinstance(items, list) or any(not isinstance(m, dict) for m in items):
        raise ValueError(tr("问 AI 的模型名单必须是对象数组"))
    for k, m in enumerate(items):
        if m.get("engine") in ("claude", "codex"):
            where = f"chat.models[{k}]"
            check_model(m.get("model") or "", where + ".model")
            for key in ("reasoning_effort", "service_tier"):
                check_word(m.get(key) or "", f"{where}.{key}")


def check_patch(patch: dict) -> None:
    """POST /api/config 的整个补丁：任何一处不合法就整个拒绝（调用方在写盘之前调用）。"""
    for name in ("claude", "codex"):
        if name in patch:
            check_section(name, patch[name])
    if "chat" in patch:
        chat = patch["chat"]
        if not isinstance(chat, dict):
            raise ValueError(tr("{field} 必须是对象", field="chat"))
        if "models" in chat:
            check_chat_models(chat["models"])
        if "default" in chat and type(chat["default"]) is not str:
            raise ValueError(tr("{field} 必须是字符串", field="chat.default"))
