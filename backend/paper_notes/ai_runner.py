"""呼叫本機 claude / codex CLI，取回符合 JSON schema 的結果。旗標已於 2026-10-01 實測。"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

Engine = Literal["claude", "codex"]
DEFAULT_TIMEOUT = 300
_CLAUDE_DENY = ["Agent", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]


class AIError(Exception):
    """CLI 找不到、逾時或回報錯誤。訊息直接給使用者看。"""


def _bin(engine: str) -> str:
    return os.environ.get(f"PAPER_NOTES_{engine.upper()}_BIN", engine)


def claude_command(schema: dict) -> list[str]:
    return [_bin("claude"), "-p", "--output-format", "json", "--strict-mcp-config",
            "--no-session-persistence", "--allowedTools", "Read", "Skill",
            "--disallowedTools", *_CLAUDE_DENY, "--json-schema", json.dumps(schema)]


def codex_command(workdir: Path, schema_file: Path, out_file: Path) -> list[str]:
    return [_bin("codex"), "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
            "--color", "never", "-C", str(workdir), "--output-schema", str(schema_file),
            "-o", str(out_file), "-"]


def _tail(text: str, n: int = 800) -> str:
    return text[-n:]


def run(engine: Engine, prompt: str, schema: dict, workdir: Path,
        timeout: int = DEFAULT_TIMEOUT) -> dict:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        out_file = tmp / "out.json"
        if engine == "claude":
            cmd = claude_command(schema)
        elif engine == "codex":
            schema_file = tmp / "schema.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            cmd = codex_command(workdir, schema_file, out_file)
        else:
            raise AIError(f"未知的引擎：{engine}")
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  cwd=workdir, timeout=timeout)
        except FileNotFoundError:
            raise AIError(f"找不到 {engine} CLI，請確認已安裝並在 PATH 上") from None
        except PermissionError:
            raise AIError(f"{engine} CLI 沒有執行權限，請修復執行權限（chmod +x）或重新安裝") from None
        except subprocess.TimeoutExpired:
            raise AIError(f"{engine} 超過 {timeout} 秒未完成，已中止") from None
        if engine == "claude":
            return _parse_claude(proc)
        return _parse_codex(proc, out_file)


def _parse_claude(proc: subprocess.CompletedProcess) -> dict:
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AIError(f"claude 輸出不是 JSON（exit {proc.returncode}）："
                      f"{_tail(proc.stdout + proc.stderr)}") from None
    if data.get("is_error") or data.get("subtype") != "success":
        raise AIError(f"claude 回報錯誤：{_tail(str(data.get('result', '')))}")
    out = data.get("structured_output")
    if not isinstance(out, dict):
        raise AIError("claude 沒有回傳 structured_output")
    return out


def _parse_codex(proc: subprocess.CompletedProcess, out_file: Path) -> dict:
    if proc.returncode != 0 or not out_file.exists():
        raise AIError(f"codex 失敗（exit {proc.returncode}）：{_tail(proc.stderr or proc.stdout)}")
    try:
        out = json.loads(out_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise AIError(f"codex 輸出不是 JSON：{_tail(out_file.read_text(encoding='utf-8'))}") from None
    if not isinstance(out, dict):
        raise AIError("codex 輸出不是 JSON 物件")
    return out


def check_engine(engine: Engine) -> dict:
    if engine == "claude":
        cmd, fix = [_bin("claude"), "auth", "status"], "在終端機執行 claude，依提示登入"
    else:
        cmd, fix = [_bin("codex"), "login", "status"], "在終端機執行 codex login"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return {"ok": False, "detail": f"找不到 {engine} CLI", "fix": f"安裝 {engine} 並確認在 PATH 上"}
    except PermissionError:
        return {"ok": False, "detail": f"{engine} CLI 沒有執行權限",
                "fix": f"在終端機以 chmod +x 修復 {engine} CLI 的執行權限，或重新安裝 {engine}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{engine} 狀態檢查逾時", "fix": fix}
    logged_in = proc.returncode == 0
    if engine == "claude" and logged_in:
        try:
            logged_in = json.loads(proc.stdout).get("loggedIn") is True
        except json.JSONDecodeError:
            pass
    if logged_in:
        return {"ok": True, "detail": "已登入"}
    return {"ok": False, "detail": f"{engine} 未登入", "fix": fix}
