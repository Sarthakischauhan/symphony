"""Slash commands use session artifacts while retaining backend compatibility."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from coding_agent.persistence.jsonl import JsonlPersistence
from coding_agent.protocols import commands

SESSION_ID = "0876c78a-9f47-4bd5-a495-a8e912c3757c"


def make_agent(workspace, persistence=None, session_id=SESSION_ID):
    agent = SimpleNamespace(
        workspace=workspace,
        session_id=session_id,
        persistence=persistence,
        mode="build",
        harness=SimpleNamespace(reasoning_effort=None),
    )
    agent.set_mode = lambda mode: setattr(agent, "mode", mode)
    return agent


@pytest.mark.parametrize("session_id", [SESSION_ID, "session-test"])
def test_state_is_saved_and_loaded_within_session_bundle(tmp_path, monkeypatch, session_id):
    home = tmp_path / "home"
    monkeypatch.setattr(commands, "symphony_dir", lambda: home)
    persistence = JsonlPersistence(tmp_path / "sessions")
    agent = make_agent(tmp_path, persistence, session_id)

    assert asyncio.run(commands.execute(agent, "/mode plan")) == "Switched to plan mode."
    assert asyncio.run(commands.execute(agent, "/effort high")) == "Reasoning effort: high."
    state = persistence.session_dir(session_id) / "state.json"
    assert json.loads(state.read_text()) == {"mode": "plan", "effort": "high"}
    assert not (home / "protocols").exists()

    resumed = make_agent(tmp_path, persistence, session_id)
    commands.load_state(resumed)
    assert resumed.mode == "plan"
    assert resumed.harness.reasoning_effort == "high"


def test_legacy_state_is_migrated_to_bundle_on_load(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path / "home")
    legacy = commands._state_path(SESSION_ID)
    legacy.parent.mkdir(parents=True)
    original = '{"mode": "plan", "effort": "low", "extra": "preserved"}\n'
    legacy.write_text(original)
    persistence = JsonlPersistence(tmp_path / "sessions")
    agent = make_agent(tmp_path, persistence)

    commands.load_state(agent)

    assert agent.mode == "plan"
    assert agent.harness.reasoning_effort == "low"
    assert (persistence.session_dir(SESSION_ID) / "state.json").read_text() == original
    assert not legacy.exists()


def test_legacy_state_is_preserved_when_command_updates_it(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path / "home")
    legacy = commands._state_path(SESSION_ID)
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"mode": "plan", "extra": "preserved"}))
    persistence = JsonlPersistence(tmp_path / "sessions")
    agent = make_agent(tmp_path, persistence)

    asyncio.run(commands.execute(agent, "/effort default"))

    state = persistence.session_dir(SESSION_ID) / "state.json"
    assert json.loads(state.read_text()) == {
        "mode": "plan", "extra": "preserved", "effort": "default",
    }
    assert not legacy.exists()


def test_existing_bundle_state_takes_precedence_over_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path / "home")
    legacy = commands._state_path(SESSION_ID)
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"mode": "plan", "effort": "high"}')
    persistence = JsonlPersistence(tmp_path / "sessions")
    state = persistence.session_dir(SESSION_ID) / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"mode": "build", "effort": "default"}')
    agent = make_agent(tmp_path, persistence)
    agent.harness.reasoning_effort = "low"

    commands.load_state(agent)

    assert agent.mode == "build"
    assert agent.harness.reasoning_effort is None
    assert legacy.exists()


@pytest.mark.parametrize("backend", [None, SimpleNamespace(session_dir=Mock())])
def test_non_jsonl_backend_retains_legacy_state_location(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path / "home")
    agent = make_agent(tmp_path, backend)

    asyncio.run(commands.execute(agent, "/plan"))

    assert json.loads(commands._state_path(SESSION_ID).read_text()) == {"mode": "plan"}
    resumed = make_agent(tmp_path, backend)
    commands.load_state(resumed)
    assert resumed.mode == "plan"
    if backend is not None:
        backend.session_dir.assert_not_called()


def test_mock_without_persistence_keeps_legacy_state(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path / "home")
    agent = make_agent(tmp_path)
    del agent.persistence

    asyncio.run(commands.execute(agent, "/plan"))

    assert commands._state_path(SESSION_ID).is_file()


def test_non_uuid_mock_without_state_can_load(tmp_path):
    agent = make_agent(tmp_path, session_id="session-test")
    commands.load_state(agent)
    assert agent.mode == "build"


def test_session_command_delegates_to_report(tmp_path, monkeypatch):
    from coding_agent.persistence import presentation

    report = AsyncMock(return_value="Session archive report")
    monkeypatch.setattr(presentation, "session_report", report)
    agent = make_agent(tmp_path)

    assert asyncio.run(commands.execute(agent, "/session")) == "Session archive report"
    report.assert_awaited_once_with(agent)


def test_learning_command_uses_agent_store_including_mock(tmp_path, monkeypatch):
    from coding_agent.learning import store

    fallback = Mock(side_effect=AssertionError("must not create a workspace store"))
    monkeypatch.setattr(store, "LearningStore", fallback)
    agent = make_agent(tmp_path)
    agent.learning_store = Mock()
    agent.learning_store.to_markdown.return_value = "Session lessons"

    assert asyncio.run(commands.execute(agent, "/learning")) == "Session lessons"
    agent.learning_store.to_markdown.assert_called_once_with()
    fallback.assert_not_called()


@pytest.mark.parametrize("has_attribute", [False, True])
def test_learning_command_falls_back_for_lightweight_agents(tmp_path, monkeypatch, has_attribute):
    from coding_agent.learning import store

    fallback_store = Mock()
    fallback_store.to_markdown.return_value = "Workspace lessons"
    fallback = Mock(return_value=fallback_store)
    monkeypatch.setattr(store, "LearningStore", fallback)
    agent = make_agent(tmp_path)
    if has_attribute:
        agent.learning_store = None

    assert asyncio.run(commands.execute(agent, "/learning")) == "Workspace lessons"
    fallback.assert_called_once_with(tmp_path)
    fallback_store.to_markdown.assert_called_once_with()
