"""The harness loop calls browser tools and its last message is the answer."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core_ai.providers.base import BaseProvider
from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent
from fakes import MemorySession

from browser_agent.agent import BrowserAgent
from browser_agent.models import Element, Observation

GOAL = "Search for travel and report the price of The Alps Guide."


class ScriptedChat(BaseProvider):
    """Plays the catalog task as tool calls, then answers from the page."""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, model_name: str, messages: list[Message], tools: list[dict[str, Any]] = [], **kwargs: Any):
        del model_name, tools, kwargs
        self.calls += 1
        last = messages[-1]
        text = last.content if isinstance(last.content, str) else ""
        if "$18" in text:
            yield StreamEvent(type="text_delta", delta="The Alps Guide costs $18.")
            yield StreamEvent(type="done")
            return
        if "travel" in text and "Search books" in text:
            async for event in _emit_call("c-click", "click", {"index": 2}):
                yield event
            return
        async for event in _emit_call("c-type", "type_text", {"index": 1, "text": "travel"}):
            yield event


class ScrollChat(BaseProvider):
    """Never stops calling a tool, so the harness hits its turn cap."""

    async def stream(self, model_name: str, messages: list[Message], tools: list[dict[str, Any]] = [], **kwargs: Any):
        del model_name, messages, tools, kwargs
        async for event in _emit_call("c-scroll", "scroll_down", {}):
            yield event


class BrokenChat(BaseProvider):
    async def stream(self, model_name: str, messages: list[Message], tools: list[dict[str, Any]] = [], **kwargs: Any):
        del model_name, messages, tools, kwargs
        raise RuntimeError("gateway down")
        yield StreamEvent(type="done")


class EmptyChat(BaseProvider):
    async def stream(self, model_name: str, messages: list[Message], tools: list[dict[str, Any]] = [], **kwargs: Any):
        del model_name, messages, tools, kwargs
        yield StreamEvent(type="done")


async def _emit_call(call_id: str, name: str, args: dict[str, Any]):
    """The harness reads the name from toolcall_start and the JSON from toolcall_delta."""
    yield StreamEvent(type="toolcall_start", tool_call_id=call_id, tool_name=name)
    yield StreamEvent(type="toolcall_delta", tool_call_id=call_id, delta=json.dumps(args))
    yield StreamEvent(type="done")


def _agent(provider: BaseProvider, **kwargs: Any) -> BrowserAgent:
    registry = ModelRegistry()
    registry.register("fake", provider)
    return BrowserAgent(registry=registry, model_id="fake:chat", **kwargs)


def _kinds(agent: BrowserAgent) -> list[str]:
    return [event.event_type for event in agent.sink.events]


def test_harness_drives_the_catalog_and_answers() -> None:
    agent = _agent(ScriptedChat(), max_steps=6)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "done"
    assert (result.provider, result.model) == ("fake", "chat")
    assert result.output_text == "The Alps Guide costs $18."
    kinds = _kinds(agent)
    assert kinds[0] == "run_started"
    assert "run_completed" in kinds
    assert "tool_execution_started" in kinds
    started = next(event for event in agent.sink.events if event.event_type == "run_started")
    assert started.payload["agent_id"] == "browser"
    assert "type_text" in started.payload["tool_names"]


def test_turn_cap_is_limited() -> None:
    agent = _agent(ScrollChat(), max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "limited"
    assert "max_turns" in result.message


def test_model_failure_is_error() -> None:
    agent = _agent(BrokenChat(), max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "error"
    assert "gateway down" in result.message


def test_no_answer_is_blocked() -> None:
    agent = _agent(EmptyChat(), max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "blocked"
    assert result.output_text == ""


def test_missing_model_is_error_without_a_run() -> None:
    agent = BrowserAgent(registry=ModelRegistry(), model_id="", max_steps=2)
    result = asyncio.run(agent.run(GOAL, MemorySession()))
    assert result.status == "error"
    assert agent.sink.events == []


def test_secret_values_are_not_typed_back_to_the_model() -> None:
    class PasswordPage:
        def __init__(self) -> None:
            self.typed = ""

        async def observe(self) -> Observation:
            field = Element(index=1, role="input", name="Enter code", value=self.typed, kind="type", secret=True)
            return Observation(url="https://example.test/login", title="Login", text="Login", elements=[field])

        async def act(self, decision) -> None:
            self.typed = decision.type_value

    class Typist(BaseProvider):
        async def stream(self, model_name, messages, tools=None, **kwargs):
            del model_name, tools, kwargs
            last = messages[-1].content if isinstance(messages[-1].content, str) else ""
            if "s3cret" in last and "Elements:" in last:
                raise AssertionError("secret value was shown to the model")
            if messages[-1].role == "tool":
                yield StreamEvent(type="text_delta", delta="Typed.")
                yield StreamEvent(type="done")
                return
            async for event in _emit_call("c-type", "type_text", {"index": 1, "text": "s3cret"}):
                yield event

    page = PasswordPage()
    result = asyncio.run(_agent(Typist()).run("Type the code.", page))
    assert page.typed == "s3cret"
    assert result.output_text == "Typed."


def test_reused_agent_gets_a_new_run_id() -> None:
    agent = _agent(ScriptedChat(), max_steps=6)
    asyncio.run(agent.run(GOAL, MemorySession()))
    asyncio.run(agent.run(GOAL, MemorySession()))
    starts = [event.payload for event in agent.sink.events if event.event_type == "run_started"]
    assert starts[0]["run_id"] != starts[1]["run_id"]
