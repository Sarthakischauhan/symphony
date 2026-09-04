from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from coding_agent.credentials import (
    global_env_path,
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
    "XAI_API_KEY",
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


def test_upsert_dotenv_sets_owner_only_mode(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    upsert_dotenv(path, {"OPENAI_API_KEY": "secret"})
    if os.name != "posix":
        pytest.skip("mode bits are POSIX-only")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    upsert_dotenv(path, {"OPENAI_API_KEY": "updated"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_provider_key_writes_global_env_and_process_env(tmp_path: Path) -> None:
    spec = save_provider_key("anthropic", "  sk-ant-test  ")
    assert spec.id == "anthropic"
    env_path = global_env_path()
    assert env_path == (Path.home() / ".symphony" / ".env").resolve()
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env_path.read_text(encoding="utf-8")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert not workspace_env_path(tmp_path).exists()
    if os.name == "posix":
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_save_provider_key_rejects_empty_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        save_provider_key("openai", "   ")
    assert not global_env_path().exists()
    assert not workspace_env_path(tmp_path).exists()


def test_load_provider_env_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    global_path = global_env_path()
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        "OPENAI_API_KEY=from-global\n"
        "ANTHROPIC_API_KEY=from-global\n"
        "GEMINI_API_KEY=from-global\n",
        encoding="utf-8",
    )
    workspace_env_path(workspace).write_text(
        "OPENAI_API_KEY=from-workspace\nANTHROPIC_API_KEY=from-workspace\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "from-process")

    load_provider_env(workspace)

    assert os.environ["OPENAI_API_KEY"] == "from-process"
    assert os.environ["ANTHROPIC_API_KEY"] == "from-workspace"
    assert os.environ["GEMINI_API_KEY"] == "from-global"


def test_load_provider_env_reads_global_when_workspace_missing(
    tmp_path: Path,
) -> None:
    global_path = global_env_path()
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text("OPENAI_API_KEY=from-global\n", encoding="utf-8")

    load_provider_env(tmp_path)

    assert os.environ["OPENAI_API_KEY"] == "from-global"
    assert not workspace_env_path(tmp_path).exists()
