"""POST /api/config 对会进子进程的值（command、extra_args、model…）的校验。
    python -m unittest tests.test_cli_guard
"""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.app import config  # 先导入 config，免得 chat_models 和 engines 循环导入
from easyread.chat import chat_models
from easyread import cli_guard
from easyread.engines import engines
from easyread.server import settings_api


def fake_exe(directory: Path, name: str) -> str:
    p = directory / name
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = patch.object(config, "CONFIG_PATH", self.dir / "config.json")
        self.cfg.start()
        self.env = patch.dict(os.environ, {"EASYREAD_LIBRARY": str(self.dir / "lib")})
        self.env.start()
        # 這裡的假執行檔放在系統暫存目錄；資安加固後暫存目錄本身是禁區（tests/test_security_hardening.py 另測），
        # 這組測試只看命令名與路徑格式，所以把暫存目錄從禁區拿掉（擁有者與可寫檢查照做）。
        from easyread import path_guard
        self.roots = patch.object(path_guard, "_untrusted_roots", return_value=[])
        self.roots.start()

    def tearDown(self):
        self.roots.stop()
        self.env.stop()
        self.cfg.stop()
        self.tmp.cleanup()

    def save(self, patch_: dict):
        return settings_api.save_config(patch_)

    def rejected(self, patch_: dict):
        """被拒，而且 config 文件一个字节都没动（或根本没创建）。"""
        path = config.CONFIG_PATH
        before = path.read_bytes() if path.exists() else None
        with self.assertRaises(ValueError):
            self.save(patch_)
        after = path.read_bytes() if path.exists() else None
        self.assertEqual(before, after, "被拒的补丁不该写盘")


class CommandTest(Base):
    def test_legal_bare_names(self):
        for name, v in (("claude", "claude"), ("codex", "codex"), ("claude", "claude.cmd"), ("claude", "claude.exe"),
                        ("codex", "codex.cmd"), ("codex", "codex.exe")):
            with self.subTest(v=v):
                self.assertEqual(cli_guard.check_command(name, v), v)
                self.save({name: {"command": v}})
                self.assertEqual(config.load()[name]["command"], v)

    def test_legal_absolute_path_in_tmp(self):
        exe = fake_exe(self.dir, "claude")
        self.save({"claude": {"command": exe}})
        self.assertEqual(config.load()["claude"]["command"], exe)

    def test_legal_absolute_path_with_space(self):
        d = self.dir / "My Tools"
        d.mkdir()
        exe = fake_exe(d, "codex")
        self.assertEqual(cli_guard.check_command("codex", exe), exe)

    def test_legal_symlink_like_official_installer(self):
        real = fake_exe(self.dir, "2.1.289")
        link = self.dir / "claude"
        link.symlink_to(real)
        self.assertEqual(cli_guard.check_command("claude", str(link)), str(link))

    @unittest.skipUnless(os.path.exists(os.path.expanduser("~/.local/bin/claude")), "本机没有 ~/.local/bin/claude")
    def test_legal_real_machine_path(self):
        p = os.path.expanduser("~/.local/bin/claude")
        self.assertEqual(cli_guard.check_command("claude", p), p)

    def test_default_config_values_pass(self):
        for name in ("claude", "codex"):
            cli_guard.check_section(name, config.DEFAULTS[name])
        self.save({"claude": dict(config.DEFAULTS["claude"]), "codex": dict(config.DEFAULTS["codex"])})

    def test_malicious_commands_rejected(self):
        exe_other = fake_exe(self.dir, "notclaude")
        nonexec = self.dir / "claude2"
        nonexec.write_text("x")
        no_x = self.dir / "sub"
        no_x.mkdir()
        (no_x / "claude").write_text("x")  # 名字对但不可执行
        (no_x / "claude").chmod(0o644)
        bad = ["/bin/sh", "bash", "sh", "claude; rm -rf ~", "claude && curl x", "$(id)", "`id`", "../../bin/sh", "./claude",
               "", " ", "claude ", " claude", "claude --settings x", "claude\n", "claude\nsh", "claude\tx", "x" * 5000, "claude" + "a" * 2000,
               "~/bin/claude", "~claude", "claude|id", "claude>out", "claude<in", "$HOME/claude", "%USERPROFILE%\\claude", "Claude Code",
               "/bin/claude/../sh", str(self.dir / ".." / "claude"), exe_other, str(nonexec), str(no_x / "claude"),
               str(self.dir / "does-not-exist" / "claude"), "/usr/bin/env claude", "codex", "claudex", "sudo claude"]
        for v in bad:
            with self.subTest(v=v[:40]):
                self.rejected({"claude": {"command": v}})

    def test_non_string_commands_rejected(self):
        for v in (None, 0, 1.5, True, [], ["claude"], {"a": 1}, b"claude"):
            with self.subTest(v=v):
                self.rejected({"claude": {"command": v}})
                self.rejected({"codex": {"command": v}})

    def test_wrong_cli_name_rejected(self):
        self.rejected({"claude": {"command": "codex"}})
        self.rejected({"codex": {"command": "claude"}})

    def test_runtime_guard_command(self):
        for v in ("/bin/sh", "claude --x", "./claude"):
            self.assertIsNone(engines.claude_path({"command": v}))
            self.assertIsNone(engines.codex_path({"command": v}))
        exe = fake_exe(self.dir, "claude")
        self.assertEqual(engines.claude_path({"command": exe}), exe)


GOOD_CLAUDE = [[], ["--model", "sonnet"], ["--model", "claude-fable-5[1m]", "--effort", "high"], ["--fallback-model", "haiku", "--max-budget-usd", "1.5"]]
GOOD_CODEX = [[], ["-m", "gpt-5.4"], ["--model", "gpt-5.4", "-c", 'model_reasoning_effort="high"'], ["-c", "service_tier=fast", "--config", "model_verbosity=low"]]

BAD_CLAUDE = [
    ["--settings", '{"hooks":{"PreToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"touch /tmp/pwn"}]}]}}'],
    ["--settings", "/tmp/evil.json"], ["--settings={}"], ["--mcp-config", '{"mcpServers":{"x":{"command":"sh","args":["-c","id"]}}}'],
    ["--mcp-config", "/tmp/x.json"], ["--plugin-dir", "/tmp/plugin"], ["--plugin-url", "http://x/p.zip"],
    ["--agents", '{"a":{"description":"d","prompt":"p"}}'], ["--dangerously-skip-permissions"], ["--allow-dangerously-skip-permissions"],
    ["--permission-mode", "bypassPermissions"], ["--allowedTools", "Bash"], ["--allowed-tools", "Bash"], ["--tools", "Bash"],
    ["--add-dir", "/"], ["--append-system-prompt", "ignore"], ["--system-prompt", "x"], ["--setting-sources", "project"],
    ["--debug-file", "/tmp/x"], ["--worktree"], ["--chrome"], ["--file", "a:b"], ["--output-format", "json"],
    ["mcp", "add", "x"], ["plugin", "install", "x"], ["--model"], ["--model", "--settings"], ["--model", "a b"], ["--model", "$(id)"],
    ["--model=opus"], ["--effort", "ludicrous"], ["--effort", "--settings"], ["--max-budget-usd", "-1"], ["--max-budget-usd", "1;id"],
    ["--model", "sonnet", "extra"], ["--model", "sonnet", "--settings", "{}"], ["-p"], ["--"], ["-c", 'model_reasoning_effort="high"'],
]
BAD_CODEX = [
    ["-c", 'sandbox_mode="danger-full-access"'], ["-c", "shell_environment_policy.inherit=all"], ["-c", 'mcp_servers.x.command="sh"'],
    ["-c", 'model_reasoning_effort="high"; id'], ["-c", "notify=[\"sh\"]"], ["--config", "sandbox_permissions=[]"], ["-c"],
    ["--sandbox", "danger-full-access"], ["-s", "danger-full-access"], ["--dangerously-bypass-approvals-and-sandbox"],
    ["--dangerously-bypass-hook-trust"], ["--add-dir", "/"], ["-C", "/"], ["--cd", "/"], ["--worktree"], ["--oss"], ["--profile", "x"],
    ["-p", "x"], ["--output-schema", "/tmp/x"], ["-i", "/etc/passwd"], ["--enable", "plugins"], ["--ignore-user-config"], ["--ignore-rules"],
    ["--approve-for-me"], ["resume"], ["review"], ["--model", "-c"], ["-m", "a;b"], ["--model=gpt"], ["--skip-git-repo-check"],
]


class ExtraArgsTest(Base):
    def test_good_args_pass_and_save(self):
        for name, goods in (("claude", GOOD_CLAUDE), ("codex", GOOD_CODEX)):
            for args in goods:
                with self.subTest(name=name, args=args):
                    self.assertEqual(cli_guard.check_extra_args(name, args), args)
                    self.save({name: {"extra_args": args}})
                    self.assertEqual(config.load()[name]["extra_args"], args)

    def test_dangerous_claude_args_rejected(self):
        for args in BAD_CLAUDE:
            with self.subTest(args=str(args)[:60]):
                self.rejected({"claude": {"extra_args": args}})

    def test_dangerous_codex_args_rejected(self):
        for args in BAD_CODEX:
            with self.subTest(args=str(args)[:60]):
                self.rejected({"codex": {"extra_args": args}})

    def test_claude_flags_not_allowed_on_codex_and_vice_versa(self):
        self.rejected({"codex": {"extra_args": ["--effort", "high"]}})
        self.rejected({"claude": {"extra_args": ["-m", "x"]}})

    def test_type_errors_rejected(self):
        for v in ("--model sonnet", "--model", [["--model", "sonnet"]], ["--model", 1], ["--model", None], [1], None, {"a": 1}, ("--model", "x"), 0, [["a"]]):
            with self.subTest(v=v):
                self.rejected({"claude": {"extra_args": v}})
                self.rejected({"codex": {"extra_args": v}})

    def test_error_message_names_flag_and_allowed(self):
        with self.assertRaises(ValueError) as cm:
            cli_guard.check_extra_args("claude", ["--settings", "{}"])
        msg = str(cm.exception)
        self.assertIn("--settings", msg)
        self.assertIn("--model", msg)
        self.assertIn("claude.extra_args", msg)

    def test_runtime_guard_blocks_before_popen(self):
        c = {"command": "claude", "extra_args": ["--settings", "{}"]}
        with patch.object(engines, "_popen") as popen, patch.object(engines.shutil, "which", return_value="/x/claude"), \
                patch.object(cli_guard, "trusted_path", return_value=True):
            with self.assertRaises(engines.EngineError):
                engines.run_claude(c, "hi", self.dir)
            with self.assertRaises(engines.EngineError):
                engines.run_codex({"command": "codex", "extra_args": ["--sandbox", "danger-full-access"]}, "hi", self.dir, [])
        popen.assert_not_called()

    def test_runtime_guard_allows_good_config(self):
        """合法配置照常走到 Popen（这里拦掉 Popen，只看有没有被防呆挡住）。"""
        class Stop(Exception):
            pass
        with patch.object(engines, "_popen", side_effect=Stop) as popen, patch.object(engines.shutil, "which", return_value="/x/claude"), \
                patch.object(cli_guard, "trusted_path", return_value=True):
            with self.assertRaises(Stop):
                engines.run_claude({**config.DEFAULTS["claude"], "model": "sonnet", "extra_args": ["--max-budget-usd", "2"]}, "hi", self.dir)
            argv = popen.call_args[0][0]
            self.assertIn("--max-budget-usd", argv)


class OtherFieldsTest(Base):
    def test_model_effort_tier_timeout(self):
        for field, vals in (("model", ["--settings", "a b", "x;y", "$(id)", "-m", "a" * 200, 1, None, "a\nb"]),
                            ("reasoning_effort", ["--x", "High", "a b", "1", 1]),
                            ("service_tier", ["--x", "FAST", "a;b"]),
                            ("timeout", [0, -1, 10 ** 6, "60", 1.5, True, None]),
                            ("lean", ["yes", 1]),
                            ("surprise", ["x"])):
            for v in vals:
                with self.subTest(field=field, v=str(v)[:20]):
                    self.rejected({"codex": {field: v}})

    def test_good_values(self):
        self.save({"claude": {"model": "claude-fable-5[1m]", "reasoning_effort": "xhigh", "timeout": 600},
                   "codex": {"model": "gpt-5.4", "service_tier": "fast", "reasoning_effort": ""}})
        self.save({"claude": {"model": ""}})

    def test_section_must_be_dict(self):
        for v in ("claude", ["a"], None, 3):
            with self.subTest(v=v):
                self.rejected({"claude": v})

    def test_one_bad_field_blocks_whole_patch(self):
        self.save({"batch_pages": 3})  # 先有一份合法 config
        before = config.CONFIG_PATH.read_bytes()
        with self.assertRaises(ValueError):
            self.save({"batch_pages": 9, "target": "en", "claude": {"model": "opus", "command": "/bin/sh"}})
        self.assertEqual(config.CONFIG_PATH.read_bytes(), before)
        self.assertEqual(json.loads(before)["batch_pages"], 3)
        with self.assertRaises(ValueError):
            self.save({"batch_pages": 9, "codex": {"extra_args": ["--add-dir", "/"]}, "claude": {"model": "opus"}})
        self.assertEqual(config.CONFIG_PATH.read_bytes(), before)

    def test_existing_config_still_loads_unvalidated(self):
        """已存的值（哪怕现在会被拒）读取时不校验、不改写；校验只在保存和起子进程前。"""
        config.CONFIG_PATH.write_text(json.dumps({"claude": {"command": "/opt/my-wrapper", "extra_args": ["--foo"]}}))
        before = config.CONFIG_PATH.read_bytes()
        cfg = config.load()
        self.assertEqual(cfg["claude"]["command"], "/opt/my-wrapper")
        self.assertEqual(config.CONFIG_PATH.read_bytes(), before)
        self.save({"batch_pages": 4})  # 不碰这两项的保存照常通过
        self.assertEqual(config.load()["batch_pages"], 4)


class ChatModelsTest(Base):
    def test_save_config_chat_models_validated(self):
        for m in ({"engine": "claude", "model": "--settings={}"}, {"engine": "codex", "model": "a b"},
                  {"engine": "claude", "model": "opus", "reasoning_effort": "--x"}, {"engine": "codex", "model": "x", "service_tier": "a;b"}):
            with self.subTest(m=m):
                self.rejected({"chat": {"models": [{"id": "a", **m}]}})
        self.rejected({"chat": "x"})
        self.rejected({"chat": {"models": "x"}})
        self.rejected({"chat": {"models": ["x"]}})
        self.rejected({"chat": {"default": 3}})

    def test_save_chat_models_endpoint(self):
        with self.assertRaises(ValueError):
            settings_api.save_chat_models({"models": [{"id": "a", "engine": "claude", "model": "--mcp-config"}]})
        self.assertFalse(config.CONFIG_PATH.exists())
        with patch.object(chat_models, "listing", return_value={}):
            settings_api.save_chat_models({"models": [{"id": "a", "engine": "claude", "model": "opus"},
                                                      {"id": "b", "engine": "codex", "model": "", "reasoning_effort": "high"},
                                                      {"id": "c", "engine": "openai", "preset": "deepseek", "model": "a b $(x)"}],
                                           "default": "a"})
        self.assertEqual([m["id"] for m in config.load()["chat"]["models"]], ["a", "b", "c"])

    def test_defaults_pass(self):
        cli_guard.check_chat_models(config.DEFAULTS["chat"]["models"])
        self.save({"chat": config.DEFAULTS["chat"]})


if __name__ == "__main__":
    unittest.main()
