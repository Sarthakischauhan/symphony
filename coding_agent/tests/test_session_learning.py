"""Session-owned memory provenance remains separate from shared retrieval."""

import asyncio
import json
from types import SimpleNamespace

from core_ai.types import Message, StreamEvent

from coding_agent.learning import LearningAddon, LearningLoop, LearningStore, Lesson
from coding_agent.learning.addon import SessionMemoryAddon
from coding_agent.persistence import JsonlPersistence
from coding_agent.tools.memory import MemoryTool


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_memory_operations_and_lessons_are_session_owned_and_sanitized(tmp_path):
    first = tmp_path / "sessions" / "first"
    second = tmp_path / "sessions" / "second"
    a = LearningStore(tmp_path, session_dir=first)
    b = LearningStore(tmp_path, session_dir=second)
    MemoryTool(tmp_path, store=a).run("add", text="Use focused pytest tests; token=private-value")
    MemoryTool(tmp_path, store=b).run("add", target="user", text="Prefers concise responses")
    assert "focused pytest" in b.query("pytest tests")
    assert "private-value" not in (first / "memory/MEMORY.md").read_text()
    assert records(first / "memory/operations.jsonl")[0]["target"] == "memory"
    assert records(second / "memory/operations.jsonl")[0]["target"] == "user"
    a.append(Lesson(summary="Verify pytest tests", source_task="token=private-value"))
    assert len(records(first / "learning/lessons.jsonl")) == 1
    assert not (second / "learning/lessons.jsonl").exists()
    assert "private-value" not in (first / "learning/lessons.jsonl").read_text()
    # Historical session data is not a retrieval source.
    (first / "memory/MEMORY.md").write_text("- historical-only zebra instructions")
    assert a.query("historical-only zebra") == ""
    assert MemoryTool(tmp_path, store=a).run("remove", match="missing").startswith("error:")
    assert records(first / "memory/operations.jsonl")[-1]["status"] == "error"


def test_injected_context_and_reflection_are_archived_without_new_trusted_sources(tmp_path):
    root = tmp_path / "sessions" / "session"
    store = LearningStore(tmp_path, session_dir=root)
    store.memory_operation("add", text="Run pytest after editing persistence")

    class Registry:
        async def stream(self, *args, **kwargs):
            yield StreamEvent(type="text_delta", delta=json.dumps({
                "observations": [{"text": "Test persistence after edits", "topic": "testing", "confidence": 0.9}],
                "transcript_summary": "Tests passed",
            }))

    async def run():
        loop = LearningLoop(store, registry=Registry(), model_id="fake:test")
        messages = [Message(role="system", content="Base policy"),
                    Message(role="user", content="editing persistence")]
        context: dict[str, str] = {}
        await LearningAddon(loop).before_turn(messages=messages, context=context)
        assert "untrusted reference data" in context["memory"]
        assert messages[0].content == "Base policy"
        loop.capture("editing persistence", [Message(role="assistant", content="done")])
        await loop.wait()

    asyncio.run(run())
    context = records(root / "learning/context.jsonl")
    assert {item["kind"] for item in context} == {"queried", "injected", "capture"}
    assert "Test persistence" in store.query("persistence")
    assert store.pending_jobs() == []
    assert store.load() == []  # raw lessons are not the new retrieval source


def test_child_memory_tools_do_not_rebind_parent_store(tmp_path):
    persistence = JsonlPersistence(tmp_path / "sessions")
    parent_store = LearningStore(tmp_path, session_dir=persistence.session_dir("parent"))
    parent_tool = MemoryTool(tmp_path, store=parent_store)
    child = SimpleNamespace(session_id="child", tools={"memory": parent_tool}, registry=object(), model_id="fake:test")
    addon = SessionMemoryAddon(lambda sid: LearningStore(tmp_path, session_dir=persistence.session_dir(sid)))
    addon.attach(child)
    child.tools["memory"].run("add", text="Child learned to verify changes")
    assert child.tools["memory"] is not parent_tool
    assert parent_tool.learning_store is parent_store
    assert not (parent_store.session_dir / "memory/operations.jsonl").exists()
    assert (persistence.session_dir("child") / "memory/operations.jsonl").exists()
