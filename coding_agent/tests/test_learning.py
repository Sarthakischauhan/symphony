"""Tests for post-completion background reflection."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core_ai.types import Message, StreamEvent
from core_harness import HarnessResult
from core_harness.models import UsageTotals

from coding_agent import CodingAgent
from coding_agent.config import LearningConfig
from coding_agent.learning import LearningLoop, LearningStore


def _result() -> HarnessResult:
    return HarnessResult(
        output_text="fixed and tests passed",
        messages=[Message(role="assistant", content="fixed and tests passed")],
        usage=UsageTotals(total_tokens=10),
    )


class ReviewRegistry:
    def __init__(self) -> None:
        self.max_output_tokens = None

    async def stream(self, model_id, messages, tools=None, max_output_tokens=None):
        self.max_output_tokens = max_output_tokens
        payload = {
            "should_save": True,
            "summary": "Run focused tests after surgical edits",
            "worked": ["patch then test"],
            "failed": [],
            "applicable_when": ["editing existing code"],
            "confidence": 0.8,
        }
        yield StreamEvent(type="text_delta", delta=json.dumps(payload))
        yield StreamEvent(type="done")


def test_reflection_is_scheduled_and_saved(tmp_path: Path) -> None:
    async def scenario():
        store = LearningStore(tmp_path)
        registry = ReviewRegistry()
        loop = LearningLoop(store, registry=registry, model_id="test:model")
        loop.schedule("fix bug", _result())
        await loop.wait()
        return store.load(), registry.max_output_tokens

    lessons, max_output_tokens = asyncio.run(scenario())
    assert len(lessons) == 1
    assert "focused tests" in lessons[0].summary
    assert max_output_tokens == LearningConfig().max_output_tokens == 900


def test_should_save_false_is_normal(tmp_path: Path) -> None:
    class EmptyRegistry:
        async def stream(self, model_id, messages, tools=None, max_output_tokens=None):
            yield StreamEvent(type="text_delta", delta='{"should_save": false}')
            yield StreamEvent(type="done")

    async def scenario():
        store = LearningStore(tmp_path)
        loop = LearningLoop(store, registry=EmptyRegistry(), model_id="test:model")
        loop.schedule("routine question", _result())
        await loop.wait()
        return store.load()

    assert asyncio.run(scenario()) == []


def test_agent_returns_before_reflection_finishes(tmp_path: Path) -> None:
    class NeverRegistry:
        async def stream(self, model_id, messages, tools=None, max_output_tokens=None):
            await asyncio.Event().wait()
            yield StreamEvent(type="done")

    async def scenario():
        agent = CodingAgent(
            registry=NeverRegistry(),  # type: ignore[arg-type]
            model_id="test:model",
            workspace=tmp_path,
        )

        async def fake_run(*args, **kwargs):
            return _result()

        agent.harness.run = fake_run  # type: ignore[method-assign]
        result = await asyncio.wait_for(agent.run("fix"), timeout=0.1)
        pending = len(agent.learning_loop._tasks)  # noqa: SLF001
        for task in tuple(agent.learning_loop._tasks):  # noqa: SLF001
            task.cancel()
        return result, pending

    result, pending = asyncio.run(scenario())
    assert result.output_text == "fixed and tests passed"
    assert pending == 1


def test_learning_cancel_finishes_pending_reflection(tmp_path: Path) -> None:
    class NeverRegistry:
        async def stream(self, model_id, messages, tools=None, max_output_tokens=None):
            await asyncio.Event().wait()
            yield StreamEvent(type="done")

    async def scenario() -> None:
        store = LearningStore(tmp_path)
        loop = LearningLoop(store, registry=NeverRegistry(), model_id="test:model")
        loop.schedule("fix bug", _result())
        await asyncio.wait_for(loop.shutdown(), timeout=1)

    asyncio.run(scenario())


def test_relevant_lessons_are_bounded(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    from coding_agent.learning import Lesson

    store.append(Lesson(summary="Use patch for Python edits", applicable_when=["Python editing"]))
    context = store.context_for("edit a Python function")
    assert "Use patch" in context
    assert len(context) <= 1400


def test_learning_store_renders_markdown(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    assert "No lessons stored yet" in store.to_markdown()

    from coding_agent.learning import Lesson

    store.append(
        Lesson(
            summary="Prefer patch for indented edits",
            worked=["exact whitespace match"],
            failed=["stripped old_str"],
            applicable_when=["editing existing files"],
            confidence=0.8,
            source_task="fix indentation bug",
        )
    )
    markdown = store.to_markdown()
    assert markdown.startswith("# Agent learnings")
    assert "Prefer patch for indented edits" in markdown
    assert "**What worked:**" in markdown
    assert "exact whitespace match" in markdown
