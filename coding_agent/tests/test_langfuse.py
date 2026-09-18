"""Tests for optional Langfuse telemetry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from core_ai.types import Message
from core_harness.models import HarnessResult, ToolCall, ToolResult, UsageTotals

from coding_agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig
from coding_agent.langfuse import LangfuseAddon, langfuse_from_config
from coding_agent.langfuse.serialize import (
    serialize_messages,
    serialize_run_output,
    serialize_task,
    serialize_tool_arguments,
    serialize_turn_output,
)


class FakeObservation:
    def __init__(self, name: str, as_type: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.as_type = as_type
        self.kwargs = dict(kwargs)
        self.updates: list[dict[str, Any]] = []
        self.ended = False
        self.children: list[FakeObservation] = []
        self.id = f"span-{name}"
        self.trace_id = kwargs.get("trace_id") or "trace-run"

    def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
        child = FakeObservation(name, as_type, {**kwargs, "trace_id": self.trace_id})
        self.children.append(child)
        return child

    def update_trace(self, **kwargs: Any) -> None:
        self.updates.append({"trace": dict(kwargs)})

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
        if "trace_context" in kwargs:
            observation.trace_id = kwargs["trace_context"].get("trace_id", observation.trace_id)
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


def _observation_text(client: FakeLangfuse) -> str:
    blobs: list[Any] = []

    def walk(observation: FakeObservation) -> None:
        blobs.append(observation.kwargs)
        blobs.extend(observation.updates)
        for child in observation.children:
            walk(child)

    for observation in client.observations:
        walk(observation)
    return json.dumps(blobs, default=str)


def test_addon_redacts_secrets_on_every_observation_payload() -> None:
    secret = "sk-secretABCDEFG12"
    assigned = "OPENAI_API_KEY=sk-leakedkey99999"
    client = FakeLangfuse()
    addon = _addon(client)
    messages = [
        Message(role="system", content="You are Symphony."),
        Message(role="user", content=f"Fix the leak {assigned}"),
    ]

    async def scenario() -> None:
        await addon.before_run(messages=messages)
        await addon.before_turn(turn=0, messages=messages)
        messages.append(Message(
            role="assistant",
            content=f"calling bash with {secret}",
            tool_calls=[{
                "id": "c1",
                "name": "bash",
                "arguments": {"command": f"echo {assigned}"},
            }],
        ))
        tool_call = ToolCall(
            id="c1",
            name="bash",
            arguments={"command": f"echo {assigned}"},
        )
        await addon.before_tool(
            tool_name="bash",
            arguments={"command": f"echo {assigned}"},
            tool_call=tool_call,
        )
        await addon.on_tool(
            tool_call=tool_call,
            result=ToolResult(status="success", content=f"printed {secret}"),
        )
        messages.append(Message(role="tool", content=f"printed {secret}", tool_call_id="c1"))
        await addon.after_turn(turn=0, messages=messages, had_tool_calls=True)
        await addon.after_run(
            task=f"Fix the leak {assigned}",
            result=HarnessResult(
                output_text=f"done {assigned} {secret}",
                messages=messages,
                usage=UsageTotals(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            ),
        )

    asyncio.run(scenario())

    dumped = _observation_text(client)
    assert secret not in dumped
    assert assigned not in dumped
    assert "sk-leakedkey99999" not in dumped
    assert "OPENAI_API_KEY=" not in dumped
    run = client.observations[0]
    assert "[REDACTED]" in run.kwargs["input"]
    generation = run.children[0]
    turn_output = next(update["output"] for update in generation.updates if "output" in update)
    assert "[REDACTED]" in turn_output["text"]
    assert "[REDACTED]" in json.dumps(turn_output["tool_calls"], default=str)
    tool = run.children[1]
    assert "[REDACTED]" in json.dumps(tool.kwargs["input"], default=str)
    run_output = next(update["output"] for update in run.updates if "output" in update)
    assert "[REDACTED]" in run_output


def test_serialize_helpers_redact_task_tool_args_and_outputs() -> None:
    secret = "sk-secretABCDEFG12"
    assigned = "OPENAI_API_KEY=sk-leakedkey99999"
    assert secret not in serialize_task(f"do this {assigned}")
    assert assigned not in serialize_task(f"do this {assigned}")
    args = serialize_tool_arguments({"command": f"export {assigned}"})
    assert secret not in json.dumps(args)
    assert assigned not in json.dumps(args)
    turn = serialize_turn_output(
        f"here {secret}",
        [{"id": "c1", "name": "write", "arguments": {"contents": assigned}}],
    )
    dumped = json.dumps(turn)
    assert secret not in dumped
    assert assigned not in dumped
    assert secret not in serialize_run_output(f"final {assigned}")
    assert assigned not in serialize_run_output(f"final {assigned}")


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
    assert any(update.get("trace", {}).get("session_id") == "session-1" for update in run.updates)
    assert any(update.get("trace", {}).get("session_id") == "session-1" for update in run.children[1].updates)
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


def test_tools_reuse_parent_trace_when_parent_cannot_start_children() -> None:
    class RootOnlyObservation(FakeObservation):
        def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
            raise TypeError("root observation cannot nest")

    class Client:
        def __init__(self) -> None:
            self.observations: list[FakeObservation] = []
            self.flushed = 0

        def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> FakeObservation:
            observation = FakeObservation(name, as_type, kwargs)
            if "trace_context" in kwargs:
                observation.trace_id = kwargs["trace_context"]["trace_id"]
            self.observations.append(observation)
            return observation

        def flush(self) -> None:
            self.flushed += 1

    client = Client()
    addon = LangfuseAddon(client=client)
    root = RootOnlyObservation("coding-agent-run", "span", {})
    root.trace_id = "trace-run"
    root.id = "span-run"
    addon.attach(type("Harness", (), {
        "model_id": "fake:test-model",
        "session_id": "session-1",
        "_active_session_id": "session-1",
        "_active_run_id": "run-1",
        "agent_id": "agent-1",
        "parent_id": None,
    })())
    addon._run_observation = root

    async def scenario() -> None:
        tool_call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
        await addon.before_tool(tool_name="read_file", arguments={"path": "a.py"}, tool_call=tool_call)
        await addon.on_tool(tool_call=tool_call, result=ToolResult(status="success", content="ok"))

    asyncio.run(scenario())
    assert len(client.observations) == 1
    tool = client.observations[0]
    assert tool.name == "read_file"
    assert tool.kwargs["trace_context"] == {"trace_id": "trace-run", "parent_span_id": "span-run"}
    assert any(update.get("trace", {}).get("session_id") == "session-1" for update in tool.updates)


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
