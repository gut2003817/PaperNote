"""Grok Build / Antigravity / Cursor CLI：参数怎么拼、提示词怎么送进去、输出怎么读（#50）。
python -m unittest tests.engines.test_agent_cli"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from easyread.app import config
from easyread.chat import chat_models, chat_options
from easyread.engines import agent_cli, engines, usage


class FakeProc:
    returncode = 0


class AgentCliTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.calls = []

    def fake(self, out):
        """替掉起进程：记下命令行和 stdin（grok 的话连同提示词文件的内容），返回给定输出。"""
        def popen(args, cwd):
            self.calls.append({"args": args, "cwd": cwd})
            if "--prompt-file" in args:
                self.calls[-1]["file"] = Path(args[args.index("--prompt-file") + 1]).read_text(encoding="utf-8")
            return FakeProc()

        def communicate(proc, stdin_text, timeout, cancel):
            self.calls[-1]["stdin"] = stdin_text
            return out
        return mock.patch.multiple(engines, _popen=popen, _communicate=communicate)

    def run_cli(self, engine, out, c=None, meter=None):
        c = {**config.DEFAULTS[engine], **(c or {})}
        with mock.patch.object(agent_cli, "path", return_value="X:/bin/" + engine), self.fake(out):
            return agent_cli.run(engine, c, "翻译这一页", self.dir, None, meter)

    # ---------- Grok Build ----------
    def test_grok_prompt_goes_through_file_and_reads_text(self):
        out = json.dumps({"text": "好", "stopReason": "end_turn", "sessionId": "s",
                          "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0, "output_tokens": 7}})
        meter = usage.Meter("grok")
        self.assertEqual(self.run_cli("grok", out, {"model": "grok-build-0.1"}, meter), "好")
        call = self.calls[0]
        self.assertEqual(call["file"], "翻译这一页" + agent_cli.ONLY_READ)
        self.assertEqual(call["stdin"], "")
        self.assertNotIn("翻译这一页", call["args"])  # 提示词不进命令行
        self.assertEqual(call["args"][1], "--prompt-file")
        self.assertIn("--model", call["args"])
        self.assertNotIn("--always-approve", call["args"])  # 写文件、跑命令一律不放行
        a = call["args"]
        self.assertEqual(a[a.index("--tools") + 1], "read_file")  # 工具全开时它会乱跑、被拒后交白卷
        self.assertEqual(a[a.index("--reasoning-effort") + 1], "low")  # 没选推理强度时用 low
        self.assertFalse(Path(call["args"][2]).exists())  # 临时文件用完删掉
        self.assertEqual((meter.data["input"], meter.data["cached"], meter.data["output"]), (1000, 900, 7))

    def test_grok_error_object(self):
        with self.assertRaises(engines.EngineError) as e:
            self.run_cli("grok", json.dumps({"type": "error", "message": "Not signed in"}))
        self.assertIn("Not signed in", str(e.exception))

    def test_grok_pretty_printed_json(self):
        self.assertEqual(self.run_cli("grok", json.dumps({"text": "多行也能读"}, indent=2, ensure_ascii=False)), "多行也能读")

    # ---------- Antigravity CLI ----------
    def test_agy_sends_one_user_event_on_stdin(self):
        out = "\n".join(json.dumps(e) for e in [
            {"event": "init", "conversation_id": "c"},
            {"event": "step_update", "text_delta": "半"},
            {"event": "result", "result": {"status": "SUCCESS", "response": "全文\n",
                                           "usage": {"input_tokens": 300, "output_tokens": 5, "thinking_tokens": 2, "cache_read_tokens": 200}}}])
        meter = usage.Meter("agy")
        self.assertEqual(self.run_cli("agy", out, {"reasoning_effort": "high"}, meter), "全文")
        call = self.calls[0]
        self.assertEqual(json.loads(call["stdin"]), {"event": "user", "message": {"content": "翻译这一页" + agent_cli.ONLY_READ}})
        self.assertNotIn("-p", call["args"])  # stream-json 输入时 -p 的提示词会被丢掉
        self.assertEqual(call["args"][call["args"].index("--effort") + 1], "high")
        self.assertEqual((meter.data["input"], meter.data["cached"], meter.data["output"]), (300, 200, 7))

    def test_agy_unsupported_effort_not_passed(self):
        self.run_cli("agy", json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "x"}}), {"reasoning_effort": "ultra"})
        self.assertNotIn("--effort", self.calls[0]["args"])

    def test_agy_error_status(self):
        out = json.dumps({"event": "result", "result": {"status": "ERROR", "error": "authentication required"}})
        with self.assertRaises(engines.EngineError) as e:
            self.run_cli("agy", out)
        self.assertIn("authentication required", str(e.exception))

    # ---------- Cursor CLI ----------
    def test_cursor_prompt_on_stdin_read_only(self):
        out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "译文"})
        self.assertEqual(self.run_cli("cursor", out), "译文")
        call = self.calls[0]
        self.assertEqual(call["stdin"], "翻译这一页" + agent_cli.ONLY_READ)
        a = call["args"]
        self.assertEqual(a[a.index("--mode") + 1], "ask")
        self.assertIn("--trust", a)
        self.assertNotIn("--force", a)
        self.assertNotIn("--model", a)  # 模型空着用它自己的默认

    def test_cursor_error(self):
        with self.assertRaises(engines.EngineError):
            self.run_cli("cursor", json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "quota"}))

    def test_empty_output_is_error(self):
        with self.assertRaises(engines.EngineError):
            self.run_cli("cursor", "")

    # ---------- 找命令、接进引擎 ----------
    def test_path_prefers_configured_command_then_defaults(self):
        found = {"cursor-agent": "C:/x/cursor-agent.cmd"}
        with mock.patch("shutil.which", side_effect=found.get):
            self.assertEqual(agent_cli.path("cursor", {"command": ""}), "C:/x/cursor-agent.cmd")
            self.assertIsNone(agent_cli.path("cursor", {"command": "agent"}))

    def test_grok_agent_not_mistaken_for_cursor(self):
        grok_bin = self.dir / "grok-bin"
        grok_bin.mkdir()
        for n in ("grok.exe", "agent.exe"):
            (grok_bin / n).write_bytes(b"")
        found = {"agent": str(grok_bin / "agent.exe")}
        with mock.patch("shutil.which", side_effect=found.get):
            self.assertIsNone(agent_cli.path("cursor", {"command": ""}))
            self.assertEqual(agent_cli.path("cursor", {"command": "agent"}), str(grok_bin / "agent.exe"))  # 自己填的照用
        found["cursor-agent"] = "C:/cursor/cursor-agent.cmd"
        with mock.patch("shutil.which", side_effect=found.get):
            self.assertEqual(agent_cli.path("cursor", {"command": ""}), "C:/cursor/cursor-agent.cmd")

    def test_engines_dispatch_and_image_mode(self):
        cfg = config.DEFAULTS | {"engine": "agy"}
        self.assertEqual(engines.image_mode(cfg), "claude")  # 自己读原页图
        self.assertEqual(engines.engine_name("agy"), "Antigravity CLI")
        with mock.patch.object(agent_cli, "run", return_value="ok") as run, mock.patch.object(engines.netcheck, "problem", return_value=None):
            self.assertEqual(engines.run(cfg, "p", self.dir), "ok")
        self.assertEqual(run.call_args.args[0], "agy")

    def test_chat_model_card_kept_and_mapped(self):
        items = chat_models.sanitize([{"id": "g", "name": "Grok", "engine": "grok", "model": "grok-build-0.1"}])
        self.assertEqual(items[0]["engine"], "grok")
        cfg = config.DEFAULTS | {"chat": {"models": items, "default": "g"}}
        ecfg, m = chat_models.engine_cfg(cfg, "g")
        self.assertEqual((ecfg["engine"], ecfg["grok"]["model"]), ("grok", "grok-build-0.1"))
        self.assertEqual(chat_models.translation_id(ecfg), "g")

    def test_chat_effort_limits(self):
        ecfg = config.DEFAULTS | {"engine": "agy", "agy": dict(config.DEFAULTS["agy"])}
        chat_options.apply(ecfg, {"reasoning_effort": "low"})
        with self.assertRaises(ValueError):
            chat_options.apply(ecfg, {"reasoning_effort": "ultra"})
        cur = config.DEFAULTS | {"engine": "cursor", "cursor": dict(config.DEFAULTS["cursor"])}
        with self.assertRaises(ValueError):
            chat_options.apply(cur, {"reasoning_effort": "low"})


class RealProcessTest(unittest.TestCase):
    """真起一个子进程（假 CLI 是一段 Python）：提示词从 stdin 进、JSON 从 stdout 出。"""

    def test_cursor_round_trip(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        script = d / "fake_agent.py"
        script.write_text("import sys, json\nsys.stdin.reconfigure(encoding='utf-8')\nsys.stdout.reconfigure(encoding='utf-8')\n"
                          "p = sys.stdin.read()\nprint(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,"
                          " 'result': 'got:' + p + ':' + ' '.join(sys.argv[1:])}))\n", encoding="utf-8")
        long_prompt = "长" * 40000  # 比 Windows 命令行上限还长
        with mock.patch.object(agent_cli, "path", return_value=sys.executable), \
                mock.patch.object(agent_cli, "build_args", return_value=[str(script), "--mode", "ask"]):
            out = agent_cli.run("cursor", {"timeout": 60}, long_prompt, d)
        self.assertEqual(out, "got:" + long_prompt + agent_cli.ONLY_READ + ":--mode ask")


if __name__ == "__main__":
    unittest.main()
