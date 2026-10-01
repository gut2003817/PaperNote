#!/usr/bin/env python3
"""測試用假 CLI，同時扮演 claude 與 codex。

環境變數：
  FAKE_AI_RESPONSES  JSON 檔路徑，內容是回應陣列；每次呼叫依序取一個（取完重複最後一個）
  FAKE_AI_STATE      呼叫計數檔路徑
  FAKE_AI_LOG        把收到的 prompt（stdin）附加寫入此檔
  FAKE_AI_SLEEP      秒數，模擬很慢的 AI
  FAKE_AI_FAIL       設為 1 時模擬 CLI 失敗
"""
import json
import os
import sys
import time
from pathlib import Path


def next_response():
    responses = json.loads(Path(os.environ["FAKE_AI_RESPONSES"]).read_text(encoding="utf-8"))
    state = Path(os.environ["FAKE_AI_STATE"])
    i = int(state.read_text()) if state.exists() else 0
    state.write_text(str(i + 1))
    return responses[min(i, len(responses) - 1)]


def main():
    args = sys.argv[1:]
    fail = os.environ.get("FAKE_AI_FAIL") == "1"
    if args[:2] in (["auth", "status"], ["login", "status"]):
        print('{"loggedIn": false}' if fail else '{"loggedIn": true}')
        sys.exit(1 if fail else 0)

    prompt = sys.stdin.read()
    if log := os.environ.get("FAKE_AI_LOG"):
        with open(log, "a", encoding="utf-8") as f:
            f.write(prompt + "\n=====\n")
    time.sleep(float(os.environ.get("FAKE_AI_SLEEP", "0")))

    if args and args[0] == "exec":
        if fail:
            print("codex boom", file=sys.stderr)
            sys.exit(1)
        out = args[args.index("-o") + 1]
        Path(out).write_text(json.dumps(next_response(), ensure_ascii=False), encoding="utf-8")
        return
    if fail:
        print(json.dumps({"is_error": True, "subtype": "error_during_execution", "result": "claude boom"}))
        return
    print(json.dumps({"is_error": False, "subtype": "success",
                      "structured_output": next_response()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
