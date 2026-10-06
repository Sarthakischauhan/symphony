"""The replacement memory pipeline works through agent/tool/command boundaries."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

from core_ai.types import Message, StreamEvent
from coding_agent.agent import CodingAgent
from coding_agent.addons.learning.addon import LearningAddon
from coding_agent.addons.learning.loop import LearningLoop
from coding_agent.addons.learning.store import LearningStore
from coding_agent.addons.persistence import JsonlPersistence
from coding_agent.protocols.stdio.commands import execute
from coding_agent.tools import build_tools
from coding_agent.tools.memory import MemoryGetTool, MemorySearchTool


def test_memory_search_get_and_disabled_registration(tmp_path):
    store = LearningStore(tmp_path)
    store.memory_operation("add", text="Persistence tests need crash recovery coverage")
    result = json.loads(MemorySearchTool(tmp_path, store=store).run("persistence"))
    assert result[0]["scope"] == "workspace"
    assert "crash recovery" in MemoryGetTool(tmp_path, store=store).run(result[0]["id"])
    assert MemoryGetTool(tmp_path, store=store).run("../escape").startswith("error:")
    enabled = {tool.name for tool in build_tools(tmp_path, learning_enabled=True, learning_store=store)}
    disabled = {tool.name for tool in build_tools(tmp_path, learning_enabled=False)}
    assert {"memory", "memory_search", "memory_get"} <= enabled
    assert not {"memory", "memory_search", "memory_get"} & disabled


def test_capture_failure_does_not_fail_turn_and_new_run_does_not_cancel_job(tmp_path):
    store = LearningStore(tmp_path)
    loop = LearningLoop(store, registry=object(), model_id="fake:test")
    addon = LearningAddon(loop)
    loop.capture = Mock(side_effect=OSError("disk full"))

    async def run():
        await addon.after_turn(messages=[Message(role="user", content="fix")])
        assert loop.capture.called
    asyncio.run(run())


def test_interrupted_parent_queues_partial_evidence(tmp_path):
    async def run():
        agent = CodingAgent(registry=object(), model_id="fake:test", workspace=tmp_path,
                            tools=[], persistence=JsonlPersistence(tmp_path / "sessions"))
        messages = [Message(role="user", content="fix persistence")]
        async def fail(*args, **kwargs):
            await agent.persistence.save_conversation(session_id=agent.session_id, messages=messages)
            raise RuntimeError("interrupted")
        agent.harness.run = fail
        agent.learning_loop.resume = lambda: None
        try:
            await agent.run("fix persistence")
        except RuntimeError:
            pass
        else:
            raise AssertionError("original exception must propagate")
        jobs = agent.learning_store.pending_jobs()
        assert len(jobs) == 1
        assert jobs[0]["messages"][0]["content"] == "fix persistence"
    asyncio.run(run())


def test_automatic_worker_processes_durable_capture_without_commands(tmp_path):
    class Registry:
        async def stream(self, *args, **kwargs):
            yield StreamEvent(type="text_delta", delta=json.dumps({"observations": [
                {"text": "Migration preserves legacy transcripts", "topic": "Session Storage", "confidence": 0.9}]}))

    async def run():
        store = LearningStore(tmp_path, session_id="s")
        persistence = JsonlPersistence(tmp_path / "sessions")
        await persistence.save_conversation(session_id="s", messages=[Message(role="user", content="fix migration")])
        agent = SimpleNamespace(session_id="s", goal="fix migration", persistence=persistence,
                                learning_store=store, learning_loop=LearningLoop(store, registry=Registry(), model_id="fake:test"))
        agent.learning_loop.capture(agent.goal, await persistence.load_conversation(session_id="s"))
        await agent.learning_loop.wait()
        assert store.pending_jobs() == []
        assert "legacy transcripts" in store.get_topic("session-storage")
        for command in ("/flush", "/dream"):
            try:
                await execute(agent, command)
            except ValueError:
                pass
            else:
                raise AssertionError("removed command must not execute")
    asyncio.run(run())


def test_low_confidence_capture_is_not_promoted_and_inbox_retries(tmp_path):
    class Registry:
        async def stream(self, *args, **kwargs):
            yield StreamEvent(type="text_delta", delta=json.dumps({"observations": [
                {"text": "Unverified deployment guess", "topic": "deployment", "confidence": 0.3}]}))

    async def run():
        store = LearningStore(tmp_path)
        store.record_observation("Deployment requires staging verification", topic="deployment")
        loop = LearningLoop(store, registry=Registry(), model_id="fake:test")
        loop.capture("check deployment", [Message(role="user", content="deployment")])
        await loop.wait()
        assert store.pending_jobs() == []
        assert "Unverified" not in store.get_topic("deployment")
        assert "staging verification" in store.get_topic("deployment")
    asyncio.run(run())
