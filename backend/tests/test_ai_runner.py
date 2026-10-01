from pathlib import Path

import pytest

from paper_notes import ai_runner
from paper_notes.ai_runner import AIError, check_engine, claude_command, run

SCHEMA = {"type": "object", "properties": {"content": {"type": "string"}},
          "required": ["content"], "additionalProperties": False}


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_run_returns_structured_output_and_sends_prompt_via_stdin(fake_ai, tmp_path, engine):
    fake_ai.set([{"content": "你好"}])
    assert run(engine, "讀 paper.pdf", SCHEMA, tmp_path) == {"content": "你好"}
    assert fake_ai.prompts() == ["讀 paper.pdf"]


def test_claude_command_flags_and_no_prompt_in_argv():
    cmd = claude_command(SCHEMA)
    for flag in ["-p", "--output-format", "--strict-mcp-config", "--no-session-persistence",
                 "--allowedTools", "--disallowedTools", "--json-schema"]:
        assert flag in cmd
    assert "Bash" in cmd[cmd.index("--disallowedTools"):]
    assert "--bare" not in cmd


@pytest.mark.parametrize("engine,msg", [("claude", "claude 回報錯誤"), ("codex", "codex 失敗")])
def test_cli_failure_raises(fake_ai, tmp_path, monkeypatch, engine, msg):
    monkeypatch.setenv("FAKE_AI_FAIL", "1")
    with pytest.raises(AIError, match=msg):
        run(engine, "x", SCHEMA, tmp_path)


def test_timeout_raises(fake_ai, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AI_SLEEP", "3")
    with pytest.raises(AIError, match="超過 1 秒"):
        run("claude", "x", SCHEMA, tmp_path, timeout=1)


def test_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_NOTES_CLAUDE_BIN", str(tmp_path / "nope"))
    with pytest.raises(AIError, match="找不到 claude"):
        run("claude", "x", SCHEMA, tmp_path)


def test_unknown_engine(tmp_path):
    with pytest.raises(AIError, match="未知的引擎"):
        run("gemini", "x", SCHEMA, tmp_path)  # type: ignore[arg-type]


def test_check_engine_ok_and_not_logged_in(fake_ai, monkeypatch):
    assert check_engine("claude") == {"ok": True, "detail": "已登入"}
    monkeypatch.setenv("FAKE_AI_FAIL", "1")
    res = check_engine("codex")
    assert res["ok"] is False and "未登入" in res["detail"] and res["fix"]


def test_check_engine_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_NOTES_CODEX_BIN", str(tmp_path / "nope"))
    res = check_engine("codex")
    assert res["ok"] is False and "找不到" in res["detail"]


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_run_non_executable_binary_raises_ai_error(tmp_path, monkeypatch, engine):
    binary = tmp_path / engine
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o600)
    monkeypatch.setenv(f"PAPER_NOTES_{engine.upper()}_BIN", str(binary))
    with pytest.raises(AIError, match=f"{engine} CLI.*執行權限"):
        run(engine, "x", SCHEMA, tmp_path)


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_check_engine_non_executable_binary(tmp_path, monkeypatch, engine):
    binary = tmp_path / engine
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o600)
    monkeypatch.setenv(f"PAPER_NOTES_{engine.upper()}_BIN", str(binary))
    result = check_engine(engine)
    assert result["ok"] is False
    assert engine in result["detail"] and "執行權限" in result["detail"]
    assert result["fix"] and "chmod +x" in result["fix"]
