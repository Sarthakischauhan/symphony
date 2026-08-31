"""Spawn-time settings files under ``.symphony/``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent.config import (
    CodingAgentConfig,
    ensure_spawn_settings,
    load_coding_agent_config,
    spawn_settings_path,
)
from coding_agent.agent import CodingAgent, build_agent
from coding_agent.tui.control_plane import TextualControlPlane
from core_ai.types import StreamEvent


class QuietRegistry:
    async def stream(self, model_id, messages, tools):
        del model_id, messages, tools
        yield StreamEvent(type="text_delta", delta="ok")
        yield StreamEvent(type="done")


def test_ensure_spawn_settings_writes_complete_file(tmp_path: Path) -> None:
    config = ensure_spawn_settings(tmp_path)
    path = spawn_settings_path(tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["harness"]["max_turns"] == 24
    assert payload["harness"]["tool_result_prune_tokens"] == 48_000
    assert payload["harness"]["compaction_keep_recent"] == 8
    assert payload["learning"]["enabled"] is True
    assert config.harness.max_turns == 24


def test_ensure_spawn_settings_keeps_user_overrides(tmp_path: Path) -> None:
    path = spawn_settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"harness": {"max_turns": 5}}), encoding="utf-8")
    config = ensure_spawn_settings(tmp_path)
    assert config.harness.max_turns == 5
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["harness"]["max_turns"] == 5
    assert saved["harness"]["max_tool_calls"] == 40


def test_load_coding_agent_config_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        load_coding_agent_config(tmp_path)


def test_coding_agent_accepts_settings_path(tmp_path: Path) -> None:
    settings = tmp_path / "custom.json"
    settings.write_text(
        json.dumps({"harness": {"max_turns": 7}, "learning": {"enabled": False}}),
        encoding="utf-8",
    )
    agent = CodingAgent(
        registry=QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test",
        workspace=tmp_path,
        config=settings,
        tools=[],
    )
    assert agent.harness.max_turns == 7
    assert agent.learning_loop is None
    spawn = json.loads(spawn_settings_path(tmp_path).read_text(encoding="utf-8"))
    assert spawn["harness"]["max_turns"] == 7


def test_build_agent_writes_spawn_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    agent = build_agent(
        workspace=tmp_path,
        control_plane=TextualControlPlane(workspace=tmp_path),
        enable_learning=False,
    )
    saved = json.loads(spawn_settings_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["learning"]["enabled"] is False
    assert agent.learning_loop is None
    assert isinstance(agent.config, CodingAgentConfig)
