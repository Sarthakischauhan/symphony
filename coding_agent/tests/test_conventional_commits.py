"""The local hook and CI share the same commit-message validation."""
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).resolve().parents[2] / ".github/scripts/check-commit-message.py"


@pytest.mark.parametrize("subject", ["feat: add memory", "fix(memory): repair capture", "refactor(core/ai)!: change API", "revert: remove feature"])
def test_valid_commit_messages(tmp_path, subject):
    message = tmp_path / "message"
    message.write_text(subject + "\n\nBody text\n", encoding="utf-8")
    assert subprocess.run([sys.executable, str(VALIDATOR), str(message)], check=False).returncode == 0


@pytest.mark.parametrize("subject", ["", "Fix memory", "fix: ", "unknown: change", "fix(): change", "Merge branch main"])
def test_invalid_commit_messages(tmp_path, subject):
    message = tmp_path / "message"
    message.write_text(subject, encoding="utf-8")
    assert subprocess.run([sys.executable, str(VALIDATOR), str(message)], capture_output=True, check=False).returncode == 1
