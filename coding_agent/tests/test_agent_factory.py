from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tui.agent_factory import build_agent
from coding_agent.tui.control_plane import TextualControlPlane
from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.gemini import GeminiProvider


def test_build_agent_registers_anthropic_when_only_anthropic_key_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("SYMPHONY_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    agent = build_agent(workspace=tmp_path, control_plane=TextualControlPlane())
    assert agent.harness.model_id == "anthropic:claude-sonnet-5"
    assert isinstance(agent.registry._providers["anthropic"], AnthropicProvider)


def test_build_agent_registers_gemini_when_only_gemini_key_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SYMPHONY_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    agent = build_agent(workspace=tmp_path, control_plane=TextualControlPlane())
    assert agent.harness.model_id == "gemini:gemini-3.7-flash"
    assert isinstance(agent.registry._providers["gemini"], GeminiProvider)
