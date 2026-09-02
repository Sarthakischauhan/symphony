"""Persistence tests for harness protocol + coding-agent SQLite store."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import Checkpoint, CoreHarness, HarnessConfig, NullControlPlane, Tool
from core_harness.addons.persistence import PersistenceAddon
from coding_agent.persistence import SqlitePersistence


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


def test_sqlite_persistence_roundtrip(tmp_path: Path) -> None:
    store = SqlitePersistence(tmp_path / "sessions.sqlite3")
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


def test_harness_persists_and_reloads_conversation(tmp_path: Path) -> None:
    store = SqlitePersistence(tmp_path / "harness.sqlite3")
    registry = FakeRegistry()
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="You are helpful.",
        config=HarnessConfig(context_limits={"fake:test": 1000}),
        tools=[Tool(ping)],
        control_plane=control_plane,
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
