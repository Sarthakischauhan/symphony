"""Persistence tests for harness protocol + coding-agent JSONL store."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import Checkpoint, CoreHarness, HarnessConfig, EventSink, Tool
from core_harness.addons.persistence import PersistenceAddon
from core_harness import ChildConfig, SubagentAddon
from coding_agent.persistence import JsonlPersistence


def test_child_sessions_share_store_and_restore_transcripts_by_id(tmp_path: Path) -> None:
    async def run() -> None:
        store = JsonlPersistence(tmp_path / "sessions")
        parent = CoreHarness(
            registry=FakeRegistry(), model_id="fake:test", system_prompt="parent",
            config=HarnessConfig(), session_id="parent-session", agent_id="parent",
            addons=[PersistenceAddon(store), SubagentAddon(background=True,
                configure=lambda **_: ChildConfig(addons=[PersistenceAddon(store)]))],
        )
        await parent.run("Parent task")
        response = await parent.tools["spawn_agent"].execute(
            sink=parent.sink, args={"prompt": "Child task"})
        child_id = json.loads(response)["child_id"]
        await parent.child_tasks[child_id].task
        restarted_store = JsonlPersistence(tmp_path / "sessions")
        children = await restarted_store.load_children(parent_session_id="parent-session")
        assert len(children) == 1
        assert children[0]["status"] == "completed"
        child_messages = await restarted_store.load_conversation(session_id=child_id)
        assert child_messages[-1].content == "hello"
        events = await restarted_store.load_events(session_id=child_id)
        assert events[0][0] == "run_started"
        assert any(event == "run_completed" for event, _ in events)
        assert all(payload["agent_id"] == child_id and payload["parent_id"] == "parent"
                   for _, payload in events)
        assert not any(event in {"text_delta", "reasoning_delta", "tool_call_delta"}
                       for event, _ in events)
        assert [session.session_id for session in await restarted_store.list_sessions()] == ["parent-session"]
        restarted = CoreHarness(
            registry=FakeRegistry(), model_id="fake:test", system_prompt="parent",
            config=HarnessConfig(), session_id="parent-session", agent_id="parent",
            addons=[PersistenceAddon(restarted_store), SubagentAddon(background=True)],
        )
        assert list(restarted.tools) == ["spawn_agent"]
        assert children[0]["output_text"] == "hello"

    asyncio.run(run())


def ping() -> str:
    """Simple no-arg tool."""
    return "pong"


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ):
        self.calls.append({"messages": list(messages), "tools": tools})
        yield StreamEvent(type="text_delta", content_index=0, delta="hello")
        yield StreamEvent(
            type="usage",
            prompt_tokens=5,
            completion_tokens=1,
            total_tokens=6,
        )
        yield StreamEvent(type="done", content_index=0)


def _message_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_jsonl_persistence_roundtrip(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path / "sessions")
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]

    async def _run() -> None:
        await store.save_conversation(session_id="s1", messages=messages)
        loaded = await store.load_conversation(session_id="s1")
        assert loaded == messages
        sessions = await store.list_sessions()
        assert [session.session_id for session in sessions] == ["s1"]

        checkpoint = Checkpoint(
            session_id="s1",
            turn=0,
            messages=messages,
            status="completed",
            metadata={"output_text": "hello"},
        )
        await store.save_checkpoint(checkpoint=checkpoint)
        latest = await store.load_checkpoint(session_id="s1")
        assert latest is not None
        assert latest.status == "completed"
        assert latest.metadata["output_text"] == "hello"
        assert latest.messages[-1].content == "hello"

    asyncio.run(_run())


def test_jsonl_save_appends_until_history_rewrites(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path / "sessions")
    first = [
        Message(role="system", content="sys"),
        Message(role="user", content="hi"),
    ]
    grown = first + [Message(role="assistant", content="hello")]
    compacted = [
        Message(role="system", content="sys"),
        Message(role="user", content="summary"),
    ]
    path = tmp_path / "sessions" / "s1.jsonl"

    async def _run() -> None:
        await store.save_conversation(session_id="s1", messages=first)
        await store.save_conversation(session_id="s1", messages=grown)
        kinds = [entry["type"] for entry in _message_lines(path)]
        assert kinds == ["header", "message", "message", "message"]
        await store.save_conversation(session_id="s1", messages=compacted)
        loaded = await store.load_conversation(session_id="s1")
        assert loaded == compacted
        kinds = [entry["type"] for entry in _message_lines(path)]
        assert kinds[0] == "header"
        # Compaction is an append-only checkpoint; the original messages remain
        # available to the transcript/TUI view.
        assert kinds.count("message") == 3
        transcript = await store.load_transcript(session_id="s1")
        assert [message.content for message in transcript] == ["sys", "hi", "hello"]

    asyncio.run(_run())


def test_jsonl_skips_token_deltas(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path / "sessions")

    async def _run() -> None:
        await store.append_event(event_type="run_started", payload={
            "session_id": "s1", "run_id": "run", "seq": 1, "model_id": "fake",
        })
        await store.append_event(event_type="text_delta", payload={
            "session_id": "s1", "run_id": "run", "seq": 2, "delta": "hello",
        })
        await store.append_event(event_type="run_completed", payload={
            "session_id": "s1", "run_id": "run", "seq": 3, "output_text": "hello",
        })
        events = await store.load_events(session_id="s1")
        assert [event for event, _ in events] == ["run_started", "run_completed"]

    asyncio.run(_run())


def test_compaction_is_append_only_and_latest_projection_is_resumed(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path / "sessions")
    session_id = "append-only"

    async def save(messages: list[Message]) -> None:
        await store.save_conversation(session_id=session_id, messages=messages)

    asyncio.run(save([
        Message(role="system", content="system prompt"),
        Message(role="user", content="original question"),
        Message(role="assistant", content="original answer"),
        Message(role="user", content="message before first compaction"),
    ]))
    asyncio.run(save([
        Message(role="system", content="system prompt"),
        Message(role="assistant", content="first compacted summary"),
        Message(role="user", content="message after first compaction"),
    ]))
    asyncio.run(save([
        Message(role="system", content="system prompt"),
        Message(role="assistant", content="first compacted summary"),
        Message(role="user", content="message after first compaction"),
        Message(role="assistant", content="newer answer"),
    ]))
    asyncio.run(save([
        Message(role="system", content="system prompt"),
        Message(role="assistant", content="second compacted summary"),
        Message(role="user", content="message after second compaction"),
    ]))

    path = tmp_path / "sessions" / f"{session_id}.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "original question" in raw
    assert "original answer" in raw
    assert "first compacted summary" in raw
    assert "newer answer" in raw
    entries = [json.loads(line) for line in raw.splitlines()]
    compactions = [entry for entry in entries if entry.get("type") == "compaction"]
    assert len(compactions) == 2
    assert compactions[0]["through_seq"] < compactions[1]["through_seq"]

    resumed = asyncio.run(store.load_conversation(session_id=session_id))
    assert [(message.role, message.content) for message in resumed] == [
        ("system", "system prompt"),
        ("assistant", "second compacted summary"),
        ("user", "message after second compaction"),
    ]
    transcript = asyncio.run(store.load_transcript(session_id=session_id))
    transcript_text = [str(message.content) for message in transcript]
    assert "original question" in transcript_text
    assert "original answer" in transcript_text
    assert "newer answer" in transcript_text


def test_harness_persists_and_reloads_conversation(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path / "sessions")
    registry = FakeRegistry()
    sink = EventSink()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="You are helpful.",
        config=HarnessConfig(context_limits={"fake:test": 1000}),
        tools=[Tool(ping)],
        sink=sink,
        addons=[PersistenceAddon(store)],
        session_id="session-a",
    )

    first = asyncio.run(harness.run("one"))
    assert first.output_text == "hello"
    assert len(registry.calls) == 1

    second = asyncio.run(harness.run("two"))
    assert second.output_text == "hello"
    assert len(registry.calls) == 2

    # Second call should see prior user/assistant turns (no duplicate system).
    second_messages = registry.calls[1]["messages"]
    roles = [message.role for message in second_messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert second_messages[1].content == "one"
    assert second_messages[2].content == "hello"
    assert second_messages[3].content == "two"

    checkpoint = asyncio.run(store.load_checkpoint(session_id="session-a"))
    assert checkpoint is not None
    assert checkpoint.status == "completed"
