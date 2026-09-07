"""Add-on attach surface: explicit register, no auto-build on CoreHarness."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core_ai.types import Message, StreamEvent
from core_harness import (
    Addon,
    ChildConfig,
    CompactionAddon,
    CoreHarness,
    HarnessConfig,
    KeepSystemRecentCompactor,
    EventSink,
    NullPersistence,
    PersistenceAddon,
    SubagentAddon,
    Tool,
)


class RecordingAddon(Addon):
    name = "recording"

    def __init__(self) -> None:
        self.hooks: list[str] = []

    def attach(self, harness: Any) -> None:
        self.harness = harness

    async def before_run(self, **_: Any) -> None:
        self.hooks.append("before_run")

    async def before_turn(self, **_: Any) -> None:
        self.hooks.append("before_turn")

    async def after_turn(self, **_: Any) -> None:
        self.hooks.append("after_turn")

    async def after_run(self, **_: Any) -> None:
        self.hooks.append("after_run")

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
    assert "compaction_started" not in [event.event_type for event in harness.sink.events]


def test_bare_harness_has_no_spawn_tool() -> None:
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn()]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(),
    )
    assert "spawn_agent" not in harness.tools
    with pytest.raises(RuntimeError, match="spawn requires a registered SubagentAddon"):
        asyncio.run(harness.spawn("go"))


def test_register_addon_mounts_compaction_and_fires_hooks() -> None:
    recorder = RecordingAddon()
    registry = ScriptedRegistry(
        [_tool_turn("ping", prompt_tokens=90), _text_turn("done", prompt_tokens=90)]
    )
    plane = EventSink()
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
        sink=plane,
        addons=[CompactionAddon(KeepSystemRecentCompactor(keep_recent=2)), recorder],
    )
    prior = [Message(role="user", content=f"earlier task {index}") for index in range(6)]
    result = asyncio.run(harness.run("go", conversation=prior))
    assert result.output_text == "done"
    assert harness.state.compactor is not None
    assert "before_run" in recorder.hooks
    assert "before_turn" in recorder.hooks
    assert "after_turn" in recorder.hooks
    assert "after_run" in recorder.hooks
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


def test_persistence_append_event_journals_identified_events() -> None:
    class Journal(NullPersistence):
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def append_event(self, *, event_type: str, payload: dict[str, Any]) -> None:
            self.events.append((event_type, dict(payload)))

    store = Journal()
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("hello")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(),
        addons=[PersistenceAddon(store)],
        session_id="s1",
        agent_id="agent-1",
    )
    asyncio.run(harness.run("one"))
    types = [event_type for event_type, _ in store.events]
    assert "run_started" in types
    assert "run_completed" in types
    assert all(payload["session_id"] == "s1" for _, payload in store.events)
    assert all(payload["agent_id"] == "agent-1" for _, payload in store.events)
    assert all("run_id" in payload and "seq" in payload for _, payload in store.events)


def test_register_addon_rejects_duplicate_name() -> None:
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn()]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="system",
        config=HarnessConfig(),
        addons=[CompactionAddon()],
    )
    with pytest.raises(ValueError, match="duplicate addon name: 'compaction'"):
        harness.register_addon(CompactionAddon())


def test_children_do_not_inherit_persistence_by_default() -> None:
    stores: list[object] = []
    orig_init = CoreHarness.__init__

    def spy(self, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        if self.parent_id is not None:
            stores.append(self.persistence)

    class MemoryStore(NullPersistence):
        pass

    store = MemoryStore()
    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("child")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="parent",
        config=HarnessConfig(),
        addons=[PersistenceAddon(store), SubagentAddon()],
        agent_id="parent-agent",
    )
    CoreHarness.__init__ = spy  # type: ignore[method-assign]
    try:
        result = asyncio.run(harness.spawn("go", label="worker"))
    finally:
        CoreHarness.__init__ = orig_init  # type: ignore[method-assign]
    assert result.output_text == "child"
    assert isinstance(harness.persistence, MemoryStore)
    assert stores and all(isinstance(item, NullPersistence) for item in stores)
    assert all(item is not store for item in stores)


def test_custom_addon_does_not_inherit_without_fork() -> None:
    class MarkerAddon(Addon):
        name = "marker"

        def attach(self, harness: Any) -> None:
            harness.marked = True

    child_names: list[list[str]] = []
    orig_init = CoreHarness.__init__

    def spy(self, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        if self.parent_id is not None:
            child_names.append([addon.name for addon in self.addons])

    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("child")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="parent",
        config=HarnessConfig(),
        addons=[MarkerAddon(), SubagentAddon()],
        agent_id="parent-agent",
    )
    assert getattr(harness, "marked", False) is True
    CoreHarness.__init__ = spy  # type: ignore[method-assign]
    try:
        asyncio.run(harness.spawn("go"))
    finally:
        CoreHarness.__init__ = orig_init  # type: ignore[method-assign]
    assert child_names == [[]]


def test_parallel_children_get_distinct_compaction_addon_instances() -> None:
    """Two concurrent spawns must not share one CompactionAddon object."""
    parent_compaction = CompactionAddon()
    child_compactions: list[CompactionAddon] = []
    orig_init = CoreHarness.__init__

    def spy(self, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        if self.parent_id is not None:
            child_compactions.extend(
                addon
                for addon in self.addons
                if isinstance(addon, CompactionAddon)
            )

    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("ok")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="parent",
        config=HarnessConfig(),
        addons=[parent_compaction, SubagentAddon()],
        agent_id="parent-agent",
    )

    async def spawn_two() -> None:
        await asyncio.gather(
            harness.spawn("task a", label="a"),
            harness.spawn("task b", label="b"),
        )

    CoreHarness.__init__ = spy  # type: ignore[method-assign]
    try:
        asyncio.run(spawn_two())
    finally:
        CoreHarness.__init__ = orig_init  # type: ignore[method-assign]

    assert len(child_compactions) == 2
    first, second = child_compactions
    assert first is not second
    assert first is not parent_compaction
    assert second is not parent_compaction
    assert id(first) != id(second)


def test_child_config_addon_factory_is_used_instead_of_forks() -> None:
    class FactoryAddon(Addon):
        name = "factory"

        def attach(self, harness: Any) -> None:
            harness.factory_mounted = True

    seen: list[object] = []
    orig_init = CoreHarness.__init__

    def spy(self, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        if self.parent_id is not None:
            seen.append(list(self.addons))

    def factory(parent: CoreHarness) -> list[Addon]:
        del parent
        return [FactoryAddon()]

    harness = CoreHarness(
        registry=ScriptedRegistry([_text_turn("child")]),  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="parent",
        config=HarnessConfig(),
        addons=[CompactionAddon(), SubagentAddon()],
        agent_id="parent-agent",
    )
    CoreHarness.__init__ = spy  # type: ignore[method-assign]
    try:
        asyncio.run(
            harness.spawn("go", child_config=ChildConfig(addon_factory=factory))
        )
    finally:
        CoreHarness.__init__ = orig_init  # type: ignore[method-assign]
    assert len(seen) == 1
    names = [addon.name for addon in seen[0]]
    assert names == ["factory"]
    assert getattr(seen[0][0], "name") == "factory"
