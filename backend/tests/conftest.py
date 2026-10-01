import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import json

import pytest

FAKE_CLI = Path(__file__).parent / "fake_cli.py"


class FakeAI:
    def __init__(self, tmp: Path):
        self.responses = tmp / "fake_responses.json"
        self.state = tmp / "fake_state"
        self.log = tmp / "fake_prompts.log"

    def set(self, responses: list) -> None:
        self.responses.write_text(json.dumps(responses, ensure_ascii=False), encoding="utf-8")
        self.state.unlink(missing_ok=True)

    def prompts(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").split("\n=====\n")[:-1]


@pytest.fixture
def fake_ai(tmp_path, monkeypatch):
    FAKE_CLI.chmod(0o755)
    fake = FakeAI(tmp_path)
    for key, value in {
        "PAPER_NOTES_CLAUDE_BIN": str(FAKE_CLI),
        "PAPER_NOTES_CODEX_BIN": str(FAKE_CLI),
        "FAKE_AI_RESPONSES": str(fake.responses),
        "FAKE_AI_STATE": str(fake.state),
        "FAKE_AI_LOG": str(fake.log),
    }.items():
        monkeypatch.setenv(key, value)
    fake.set([{}])
    return fake
