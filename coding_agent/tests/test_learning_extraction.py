"""Memory extraction against reasoning budgets, stream resets, and bad output.

The scripted registry stands in for a provider; no live API is called.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from core_ai.content import text_from_content
from core_ai.types import StreamEvent
from core_harness import EventSink

from coding_agent import CodingAgent
from coding_agent.addons.learning import LearningLoop, LearningStore
from coding_agent.addons.learning.prompts import CAPTURE_SYSTEM_PROMPT

FACT = "The deploy script is scripts/ship.sh and needs --staging first"
OBSERVATIONS = json.dumps({"observations": [{"text": FACT, "topic": "deploy", "confidence": 0.9}]})
# Catalogued reasoning model whose lowest advertised effort is "none".
REASONING_MODEL = "openai:gpt-5.4"


def _is_capture(messages) -> bool:
    return bool(messages) and text_from_content(messages[0].content) == CAPTURE_SYSTEM_PROMPT


class ReasoningRegistry:
    """Hidden reasoning tokens come out of ``max_output_tokens``, as on OpenAI.

    At the provider-default effort the model reasons for 1,500 tokens. With a
    budget too small for that plus the JSON, the reply carries no text.
    """

    LIGHT_EFFORTS = {"none", "minimal", "low"}

    def __init__(self) -> None:
        self.capture_options: list[dict] = []
        self.agent_calls: list[list] = []

    async def stream(self, model_id, messages, tools=None, max_output_tokens=None, **kwargs):
        del model_id, tools
        if not _is_capture(messages):
            self.agent_calls.append(list(messages))
            yield StreamEvent(type="text_delta", delta="ok")
            yield StreamEvent(type="done")
            return
        effort = kwargs.get("reasoning_effort")
        self.capture_options.append({"max_output_tokens": max_output_tokens, "reasoning_effort": effort})
        reasoning = 0 if effort in self.LIGHT_EFFORTS else 1500
        yield StreamEvent(type="reasoning_delta", delta="weighing which facts are durable")
        if max_output_tokens is None or max_output_tokens >= reasoning + 200:
            yield StreamEvent(type="text_delta", delta=OBSERVATIONS)
        yield StreamEvent(type="done")


def test_reasoning_model_capture_requests_light_effort_and_room_for_json(tmp_path: Path) -> None:
    registry = ReasoningRegistry()

    async def scenario() -> list[dict]:
        store = LearningStore(tmp_path)
        loop = LearningLoop(store, registry=registry, model_id=REASONING_MODEL)  # type: ignore[arg-type]
        loop.capture("how do I deploy?", [{"role": "user", "content": "deploy with scripts/ship.sh --staging"}])
        await loop.wait()
        assert store.pending_jobs() == []
        assert FACT in store.get_topic("deploy")
        return registry.capture_options

    options = asyncio.run(scenario())
    assert options[0]["reasoning_effort"] == "none"
    assert options[0]["max_output_tokens"] >= 4096


def test_empty_capture_output_is_logged_noticed_and_counted(tmp_path: Path, caplog) -> None:
    class SilentRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, tools, kwargs
            if _is_capture(messages):
                yield StreamEvent(type="reasoning_delta", delta="thinking")
            else:
                yield StreamEvent(type="text_delta", delta="ok")
            yield StreamEvent(type="done")

    sink = EventSink()

    async def scenario() -> dict:
        agent = CodingAgent(registry=SilentRegistry(), model_id="test:model",  # type: ignore[arg-type]
                            workspace=tmp_path, tools=[], sink=sink)
        await agent.run("how do I deploy?")
        await agent.wait_for_learning()
        [path] = (agent.learning_store.memory_dir / "jobs").glob("*.json")
        return json.loads(path.read_text(encoding="utf-8"))

    with caplog.at_level(logging.WARNING, logger="coding_agent.addons.learning.loop"):
        job = asyncio.run(scenario())
    assert job["attempts"] == 1
    assert job["status"] == "pending"
    assert any(record.levelno == logging.WARNING and "no usable output" in record.getMessage()
               for record in caplog.records)
    notices = [event.payload for event in sink.events
               if event.event_type == "run_summary" and event.payload.get("label") == "memory capture"]
    assert notices and "no usable output" in notices[0]["summary"]


def test_stream_reset_drops_partial_capture_text(tmp_path: Path) -> None:
    class ResettingRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            yield StreamEvent(type="text_delta", delta=OBSERVATIONS[:30])
            yield StreamEvent(type="retry", retry_after=0.0, retry_attempt=1,
                              retry_reason="transport", retry_resets_stream=True)
            yield StreamEvent(type="text_delta", delta=OBSERVATIONS)
            yield StreamEvent(type="done")

    async def scenario() -> LearningStore:
        store = LearningStore(tmp_path)
        loop = LearningLoop(store, registry=ResettingRegistry(), model_id="test:model")  # type: ignore[arg-type]
        loop.capture("how do I deploy?", [{"role": "user", "content": "deploy with scripts/ship.sh"}])
        await loop.wait()
        return store

    store = asyncio.run(scenario())
    assert store.pending_jobs() == []
    assert FACT in store.get_topic("deploy")


def test_repeated_bad_output_marks_job_failed_and_stops_retrying(tmp_path: Path) -> None:
    calls: list[int] = []

    class GarbageRegistry:
        async def stream(self, model_id, messages, tools=None, **kwargs):
            del model_id, messages, tools, kwargs
            calls.append(1)
            yield StreamEvent(type="text_delta", delta="Sure! Here are the facts I found.")
            yield StreamEvent(type="done")

    async def scenario() -> tuple[dict, list]:
        store = LearningStore(tmp_path)
        loop = LearningLoop(store, registry=GarbageRegistry(), model_id="test:model")  # type: ignore[arg-type]
        job_id = loop.capture("how do I deploy?", [{"role": "user", "content": "deploy"}])
        for _ in range(6):  # six later runs, each resuming the worker
            loop.resume()
            await loop.wait()
        job = json.loads((store.memory_dir / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))
        return job, store.pending_jobs()

    job, pending = asyncio.run(scenario())
    assert job["status"] == "failed"
    assert pending == []
    assert len(calls) == job["attempts"] < 6


def test_reasoning_model_learns_in_turn_one_and_turn_two_request_has_it(tmp_path: Path) -> None:
    registry = ReasoningRegistry()

    async def scenario() -> list:
        agent = CodingAgent(registry=registry, model_id=REASONING_MODEL,  # type: ignore[arg-type]
                            workspace=tmp_path, tools=[])
        first = await agent.run("how do I deploy? use scripts/ship.sh")
        await agent.wait_for_learning()
        await agent.run("now deploy it again", conversation=first.messages)
        return registry.agent_calls[-1]

    request = asyncio.run(scenario())
    notes = [text_from_content(message.content) for message in request
             if message.role == "user" and FACT in text_from_content(message.content)]
    assert notes, "turn 2's model request must carry the fact learned in turn 1"
    assert text_from_content(request[-1].content) == "now deploy it again"


def test_stored_legacy_learning_off_is_turned_on(tmp_path: Path) -> None:
    from coding_agent.config import ensure_spawn_settings, spawn_settings_path

    path = spawn_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_spawn_settings used to persist enabled=false as the product default.
    path.write_text(json.dumps({"learning": {"enabled": False}}), encoding="utf-8")
    resolved = ensure_spawn_settings(tmp_path)
    assert resolved.learning.enabled is True
    assert json.loads(path.read_text(encoding="utf-8"))["learning"]["enabled"] is True
    # A learning block the user actually edited is left alone.
    path.write_text(
        json.dumps({"learning": {"enabled": False, "max_lessons": 12}}),
        encoding="utf-8",
    )
    assert ensure_spawn_settings(tmp_path).learning.enabled is False


def test_stored_old_capture_cap_is_raised_and_rewritten(tmp_path: Path) -> None:
    from coding_agent.config import ensure_spawn_settings, spawn_settings_path

    path = spawn_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_spawn_settings used to persist the old 900-token default here.
    path.write_text(json.dumps({"learning": {"max_output_tokens": 900}}), encoding="utf-8")
    resolved = ensure_spawn_settings(tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))["learning"]["max_output_tokens"]
    assert resolved.learning.max_output_tokens == stored >= 4096
    path.write_text(json.dumps({"learning": {"max_output_tokens": 20000}}), encoding="utf-8")
    assert ensure_spawn_settings(tmp_path).learning.max_output_tokens == 20000
