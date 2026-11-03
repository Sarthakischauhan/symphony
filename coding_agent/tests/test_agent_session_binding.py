"""``CodingAgent`` owns switching sessions and reading a session's saved cost."""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent import CodingAgent
from scripted_registry import ScriptedRegistry


def _agent(workspace: Path, **kwargs: object) -> CodingAgent:
    return CodingAgent(registry=ScriptedRegistry({}), model_id="fake:test", workspace=workspace, **kwargs)  # type: ignore[arg-type]


def test_bind_session_moves_the_agent_harness_and_learning_store(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.bind_session("next-session")
    assert agent.session_id == agent.harness.session_id == agent.learning_store.session_id == "next-session"
    assert agent.learning_store.session_dir == agent.persistence.session_dir("next-session").resolve()


def test_session_costs_reads_what_the_store_saved(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    assert agent.session_costs("s1") == {}
    agent.persistence.record_message_cost("s1", "openai:gpt-6-luna", 0.25)
    assert agent.session_costs("s1") == {"openai:gpt-6-luna": 0.25}
    assert agent.session_costs("other") == {}


class _InMemory:
    """A persistence that keeps nothing on disk."""

    async def load_resume(self, *, session_id: str):
        return [], []


def test_a_store_that_is_not_on_disk_has_no_cost_and_keeps_the_learning_directory(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.persistence = _InMemory()  # type: ignore[assignment]
    before = agent.learning_store.session_dir
    assert agent.session_costs("s1") == {}
    agent.bind_session("s2")
    assert agent.session_id == agent.learning_store.session_id == "s2"
    assert agent.learning_store.session_dir == before


def test_new_binds_the_real_agent_and_registers_the_session(tmp_path: Path) -> None:
    from coding_agent.tui.app import CodingAgentApp

    app = CodingAgentApp(workspace=tmp_path)
    agent = _agent(tmp_path)
    old = agent.session_id

    async def _run() -> None:
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            app._agent = agent
            await app._run_slash_command("/new")
            await pilot.pause()
            app._agent = None

    asyncio.run(_run())
    assert agent.session_id != old and app.session_id == agent.session_id
    assert agent.harness.session_id == agent.learning_store.session_id == agent.session_id
    assert agent.learning_store.session_dir == agent.persistence.session_dir(agent.session_id).resolve()
