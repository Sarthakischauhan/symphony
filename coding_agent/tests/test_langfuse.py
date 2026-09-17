"""Tests for optional Langfuse telemetry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core_ai.types import Message
from core_harness.models import HarnessResult, ToolCall, ToolResult, UsageTotals

from coding_agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig
from coding_agent.langfuse import LangfuseAddon, langfuse_from_config
from coding_agent.langfuse.serialize import serialize_messages


class FakeObservation:
    def __init__(self, name: str, as_type: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.as_type = as_type
        self.kwargs = dict(kwargs)
        self.updates: list[dict[str, Any]] = []
        self.ended = False
        self.children: list[FakeObservation] = []

    def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
        child = FakeObservation(name, as_type, kwargs)
        self.children.append(child)
        return child

    def update(self, **kwargs: Any) -> None:
        self.updates.append(dict(kwargs))

    def end(self) -> None:
        self.ended = True


class FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.flushed = 0

    def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
        observation = FakeObservation(name, as_type, kwargs)
        self.observations.append(observation)
        return observation

    def flush(self) -> None:
        self.flushed += 1


def _addon(client: FakeLangfuse) -> LangfuseAddon:
    addon = LangfuseAddon(client=client)
    addon.attach(type("Harness", (), {
        "model_id": "fake:test-model",
        "session_id": "session-1",
        "_active_session_id": "session-1",
        "_active_run_id": "run-1",
        "agent_id": "agent-1",
        "parent_id": None,
    })())
    return addon


def test_langfuse_from_config_respects_enabled_flag() -> None:
    assert langfuse_from_config(LangfuseConfig(enabled=False)) is None
    addon = langfuse_from_config(LangfuseConfig(enabled=True))
    assert addon is not None
    assert addon.name == "langfuse"


def test_attach_is_silent_without_keys(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    addon = LangfuseAddon()
    addon.attach(object())
    assert addon._client is None


def test_serialize_messages_redacts_secrets_and_omits_image_bytes() -> None:
    messages = [
        Message(role="system", content="Use OPENAI_API_KEY=sk-secret123456"),
        Message(
            role="user",
            content=[
                {"type": "text", "text": "look at this"},
                {"type": "image", "media_type": "image/png", "data": "AAA", "filename": "shot.png"},
            ],
        ),
    ]
    serialized = serialize_messages(messages)
    assert serialized[0]["content"] == "Use OPENAI_API_KEY[REDACTED]"
    assert serialized[1]["content"] == "look at this\n[image:shot.png]"
    assert "AAA" not in serialized[1]["content"]


def test_addon_records_run_turn_and_tool() -> None:
    client = FakeLangfuse()
    addon = _addon(client)
    messages = [
        Message(role="system", content="You are Symphony."),
        Message(role="user", content="Fix the failing test"),
    ]

    async def scenario() -> None:
        await addon.before_run(messages=messages)
        await addon.before_turn(turn=0, messages=messages)
        messages.append(Message(
            role="assistant",
            content="",
            tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}],
        ))
        tool_call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
        await addon.before_tool(tool_name="read_file", arguments={"path": "a.py"}, tool_call=tool_call)
        await addon.on_tool(
            tool_call=tool_call,
            result=ToolResult(status="success", content="print('hi')"),
        )
        messages.append(Message(role="tool", content="print('hi')", tool_call_id="c1"))
        await addon.after_turn(turn=0, messages=messages, had_tool_calls=True)
        await addon.on_compact(turn=0, messages=messages, tokens_used=10, context_limit=100, context_left=90)
        await addon.after_run(
            task="Fix the failing test",
            result=HarnessResult(
                output_text="done",
                messages=messages,
                usage=UsageTotals(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            ),
        )

    asyncio.run(scenario())

    assert len(client.observations) == 1
    run = client.observations[0]
    assert run.name == "coding-agent-run"
    assert run.kwargs["input"] == "Fix the failing test"
    assert "session_id" not in run.kwargs
    assert run.ended is True
    assert client.flushed == 1
    names = [child.name for child in run.children]
    assert names == ["model-turn", "read_file", "compaction"]
    generation = run.children[0]
    assert generation.as_type == "generation"
    assert generation.kwargs["input"][0]["role"] == "system"
    assert generation.kwargs["input"][1]["content"] == "Fix the failing test"
    assert generation.ended is True
    tool = run.children[1]
    assert tool.as_type == "tool"
    assert tool.kwargs["input"] == {"path": "a.py"}
    assert tool.updates[-1]["output"]["content"] == "print('hi')"
    assert tool.ended is True


def test_addon_records_when_sdk_rejects_session_id() -> None:
    """Langfuse v4 start_observation has no session_id kwarg; that used to drop traces."""

    class StrictObservation(FakeObservation):
        def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
            allowed = {
                "input", "output", "metadata", "version", "level", "status_message",
                "completion_start_time", "model", "model_parameters", "usage_details",
                "cost_details", "prompt",
            }
            extra = set(kwargs) - allowed
            if extra:
                raise TypeError(f"unexpected keyword argument {sorted(extra)[0]!r}")
            return super().start_observation(name, as_type, **kwargs)

        def update_trace(self, **kwargs: Any) -> None:
            self.updates.append({"trace": dict(kwargs)})

    class StrictLangfuse:
        def __init__(self) -> None:
            self.observations: list[FakeObservation] = []
            self.flushed = 0

        def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> StrictObservation:
            allowed = {
                "input", "output", "metadata", "version", "level", "status_message",
                "completion_start_time", "model", "model_parameters", "usage_details",
                "cost_details", "prompt",
            }
            extra = set(kwargs) - allowed
            if extra:
                raise TypeError(f"unexpected keyword argument {sorted(extra)[0]!r}")
            observation = StrictObservation(name, as_type, kwargs)
            self.observations.append(observation)
            return observation

        def flush(self) -> None:
            self.flushed += 1

    client = StrictLangfuse()
    addon = _addon(client)  # type: ignore[arg-type]
    messages = [Message(role="user", content="hello")]

    async def scenario() -> None:
        await addon.before_run(messages=messages)
        await addon.before_turn(turn=0, messages=messages)
        await addon.after_turn(turn=0, messages=messages, had_tool_calls=False)
        await addon.after_run(
            task="hello",
            result=HarnessResult(output_text="ok", messages=messages),
        )

    asyncio.run(scenario())
    assert len(client.observations) == 1
    run = client.observations[0]
    assert run.name == "coding-agent-run"
    assert run.children[0].name == "model-turn"
    assert any(update.get("trace", {}).get("session_id") == "session-1" for update in run.updates)
    assert run.ended is True
    assert client.flushed == 1


def test_coding_agent_mounts_langfuse_by_default(tmp_path: Path) -> None:
    class QuietRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            if False:
                yield None

    agent = CodingAgent(
        registry=QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[],
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    assert any(addon.name == "langfuse" for addon in agent.harness.addons)


def test_coding_agent_can_disable_langfuse(tmp_path: Path) -> None:
    class QuietRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            if False:
                yield None

    agent = CodingAgent(
        registry=QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        tools=[],
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False),
            langfuse=LangfuseConfig(enabled=False),
        ),
    )
    assert not any(addon.name == "langfuse" for addon in agent.harness.addons)


def test_child_inherits_langfuse_addon(tmp_path: Path) -> None:
    class QuietRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            if False:
                yield None

    agent = CodingAgent(
        registry=QuietRegistry(),  # type: ignore[arg-type]
        model_id="fake:test-model",
        workspace=tmp_path,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
    )
    child_addons = agent._spawn_child_config(prompt="x").addon_factory(agent.harness)
    assert any(addon.name == "langfuse" for addon in child_addons)
