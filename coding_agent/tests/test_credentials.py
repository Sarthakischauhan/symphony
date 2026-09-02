from __future__ import annotations

import os
from pathlib import Path

import pytest

from coding_agent.credentials import (
    load_provider_env,
    save_provider_key,
    upsert_dotenv,
    workspace_env_path,
)


PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "SYMPHONY_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def test_upsert_dotenv_creates_and_updates_keys(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    upsert_dotenv(path, {"OPENAI_API_KEY": "first"})
    upsert_dotenv(path, {"ANTHROPIC_API_KEY": "second"})
    upsert_dotenv(path, {"OPENAI_API_KEY": "replaced"})

    text = path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=replaced" in text
    assert "ANTHROPIC_API_KEY=second" in text
    assert text.count("OPENAI_API_KEY=") == 1
    assert "# Symphony provider credentials" in text


def test_upsert_dotenv_preserves_comments_and_quotes_values(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# keep me\nFOO=bar\nexport BAZ=qux\n", encoding="utf-8")
    upsert_dotenv(path, {"FOO": "a value", "NEW": "ok"})

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# keep me")
    assert 'FOO="a value"' in text
    assert "export BAZ=qux" in text
    assert "NEW=ok" in text


def test_save_provider_key_writes_workspace_env_and_process_env(tmp_path: Path) -> None:
    spec = save_provider_key(tmp_path, "anthropic", "  sk-ant-test  ")
    assert spec.id == "anthropic"
    env_path = workspace_env_path(tmp_path)
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env_path.read_text(encoding="utf-8")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_save_provider_key_rejects_empty_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        save_provider_key(tmp_path, "openai", "   ")
    assert not workspace_env_path(tmp_path).exists()


def test_load_provider_env_prefers_workspace_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    workspace = tmp_path / "workspace"
    cwd.mkdir()
    workspace.mkdir()
    (cwd / ".env").write_text(
        "OPENAI_API_KEY=from-cwd\nANTHROPIC_API_KEY=from-cwd\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text("OPENAI_API_KEY=from-workspace\n", encoding="utf-8")
    monkeypatch.chdir(cwd)

    load_provider_env(workspace)

    assert os.environ["OPENAI_API_KEY"] == "from-workspace"
    assert os.environ["ANTHROPIC_API_KEY"] == "from-cwd"
