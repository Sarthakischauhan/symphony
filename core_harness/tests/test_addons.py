"""Add-on attach surface: explicit register, no auto-build on CoreHarness."""

from __future__ import annotations

import asyncio
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import (
    CompactionAddon,
    CoreHarness,
    HarnessConfig,
    KeepSystemRecentCompactor,
    NullControlPlane,
    NullPersistence,
    PersistenceAddon,
    TelemetryAddon,
    Tool,
)


class RecordingAddon:
    name = "recording"

    def __init__(self) -> None:
        self.hooks: list[str] = []

    def attach(self, harness: Any) -> None:
        self.harness = harness

    async def before_turn(self, **_: Any) -> None:
        self.hooks.append("before_turn")

    async def after_turn(self, **_: Any) -> None:
        self.hooks.append("after_turn")

    async def on_tool(self, **_: Any) -> None:
        self.hooks.append("on_tool")

    async def on_compact(self, **_: Any) -> None:
        self.hooks.append("on_compact")


class ScriptedRegistry:
    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self.turns = turns
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append(list(messages))
        events = self.turns[min(len(self.calls) - 1, len(self.turns) - 1)]
        for event in events:
            yield event


def _text_turn(text: str = "ok", prompt_tokens: int = 1) -> list[StreamEvent]:
    return [
        StreamEvent(type="text_delta", delta=text),
        StreamEvent(type="usage", prompt_tokens=prompt_tokens, completion_tokens=1, total_tokens=prompt_tokens + 1),
        StreamEvent(type="done"),
    ]


def _tool_turn(name: str, call_id: str = "call-1", prompt_tokens: int = 1) -> list[StreamEvent]:
    return [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id=call_id, tool_name=name),
        StreamEvent(type="toolcall_delta", content_index=0, delta="{}"),
        StreamEvent(type="usage", prompt_tokens=prompt_tokens, completion_tokens=1, total_tokens=prompt_tokens + 1),
        StreamEvent(type="done"),
    ]


def ping() -> str:
    return "pong"


def test_bare_harness_does_not_auto_build_compactor() -> None:
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn()]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(context_compact_threshold=20, context_target_tokens=50),
    )
    assert harness.state.compactor is None
    assert isinstance(harness.persistence, NullPersistence)
    result = asyncio.run(harness.run("hi"))
    assert result.output_text == "ok"
    assert "compaction_started" not in [event.event_type for event in harness.control_plane.events]


def test_register_addon_mounts_compaction_and_fires_hooks() -> None:
    recorder = RecordingAddon()
    registry = ScriptedRegistry(
        [_tool_turn("ping", prompt_tokens=90), _text_turn("done", prompt_tokens=90)]
    )
    plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(
            max_turns=8,
            context_limits={"fake:test": 100},
            context_compact_threshold=20,
            compaction_keep_recent=2,
        ),
        tools=[Tool(ping)],
        control_plane=plane,
        addons=[CompactionAddon(KeepSystemRecentCompactor(keep_recent=2)), recorder],
    )
    prior = [Message(role="user", content=f"earlier task {index}") for index in range(6)]
    result = asyncio.run(harness.run("go", conversation=prior))
    assert result.output_text == "done"
    assert harness.state.compactor is not None
    assert "before_turn" in recorder.hooks
    assert "after_turn" in recorder.hooks
    assert "on_tool" in recorder.hooks
    assert "on_compact" in recorder.hooks
    assert "compaction_started" in [event.event_type for event in plane.events]


def test_persistence_addon_saves_conversation() -> None:
    class MemoryStore(NullPersistence):
        def __init__(self) -> None:
            self.saved: list[list[Message]] = []

        async def save_conversation(self, *, session_id: str, messages: list[Message]) -> None:
            self.saved.append(list(messages))

        async def load_conversation(self, *, session_id: str) -> list[Message]:
            return list(self.saved[-1]) if self.saved else []

    store = MemoryStore()
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("hello")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(),
        addons=[PersistenceAddon(store)],
        session_id="s1",
    )
    asyncio.run(harness.run("one"))
    assert store.saved
    assert any(message.content == "one" for message in store.saved[-1])


def test_telemetry_addon_is_a_noop_seam() -> None:
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn()]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(),
        addons=[TelemetryAddon()],
    )
    result = asyncio.run(harness.run("hi"))
    assert result.output_text == "ok"
    assert any(addon.name == "telemetry" for addon in harness.addons)
