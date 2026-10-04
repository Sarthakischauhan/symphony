"""Session-owned memory provenance remains separate from shared retrieval."""

import asyncio
import json
from types import SimpleNamespace

from core_ai.types import Message, StreamEvent
from core_harness import HarnessResult

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
    assert not (first / "memory/MEMORY.md").exists()
    assert "private-value" not in (tmp_path / ".symphony/memory/MEMORY.md").read_text()
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
                "summary": "Test persistence after edits", "worked": ["focused pytest"],
                "transcript_summary": "Tests passed", "confidence": 0.9,
            }))

    async def run():
        loop = LearningLoop(store, registry=Registry(), model_id="fake:test")
        messages = [Message(role="system", content="Base policy"),
                    Message(role="user", content="editing persistence")]
        await LearningAddon(loop).before_turn(messages=messages)
        assert "untrusted reference data" in messages[0].content
        await loop._review_and_store("editing persistence", HarnessResult(
            output_text="done", messages=[Message(role="assistant", content="done")]))

    asyncio.run(run())
    context = records(root / "learning/context.jsonl")
    assert {item["kind"] for item in context} == {"queried", "injected", "reflection"}
    lessons = records(root / "learning/lessons.jsonl")
    assert lessons[0]["kind"] == "post_run_review"
    assert lessons[0]["worked"] == ["focused pytest"]
    assert store.load() == []  # archive is not automatically promoted to durable memory


def test_child_memory_tools_do_not_rebind_parent_store(tmp_path):
    persistence = JsonlPersistence(tmp_path / "sessions")
    parent_store = LearningStore(tmp_path, session_dir=persistence.session_dir("parent"))
    parent_tool = MemoryTool(tmp_path, store=parent_store)
    child = SimpleNamespace(session_id="child", tools={"memory": parent_tool})
    addon = SessionMemoryAddon(lambda sid: LearningStore(tmp_path, session_dir=persistence.session_dir(sid)))
    addon.attach(child)
    child.tools["memory"].run("add", text="Child learned to verify changes")
    assert child.tools["memory"] is not parent_tool
    assert parent_tool.learning_store is parent_store
    assert not (parent_store.session_dir / "memory/operations.jsonl").exists()
    assert (persistence.session_dir("child") / "memory/operations.jsonl").exists()
