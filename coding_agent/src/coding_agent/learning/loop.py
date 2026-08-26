"""Non-blocking post-run reflection using one structured model call."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent.config import DEFAULT_CODING_AGENT_CONFIG
from coding_agent.learning.prompts import REVIEWER_SYSTEM_PROMPT
from coding_agent.learning.sanitize import sanitize_task, sanitize_text
from coding_agent.learning.store import LearningStore, Lesson

logger = logging.getLogger(__name__)
class LearningReview(BaseModel):
    should_save: bool = False
    summary: str = ""
    worked: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    applicable_when: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class LearningLoop:
    def __init__(
        self,
        store: LearningStore,
        *,
        registry: ModelRegistry,
        model_id: str,
        max_output_tokens: int = DEFAULT_CODING_AGENT_CONFIG.learning.max_output_tokens,
    ) -> None:
        self.store = store
        self.registry = registry
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(self, task: str, result: HarnessResult) -> None:
        """Start reflection after a completed run without delaying its result."""
        background = asyncio.create_task(self._review_and_store(task, result))
        self._tasks.add(background)
        background.add_done_callback(self._tasks.discard)

    def cancel(self) -> None:
        """Cancel pending reflections without waiting for them to finish."""
        for task in tuple(self._tasks):
            task.cancel()

    async def wait(self) -> None:
        """Drain pending reflections during an explicit application shutdown."""
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel then finish any in-flight reflection before the TUI exits."""
        self.cancel()
        await self.wait()

    async def _review_and_store(self, task: str, result: HarnessResult) -> None:
        try:
            review = await self.review(task, result)
            if review.should_save and review.summary.strip():
                self.store.append(
                    Lesson(
                        summary=review.summary,
                        worked=review.worked,
                        failed=review.failed,
                        applicable_when=review.applicable_when,
                        confidence=review.confidence,
                        source_task=task,
                    )
                )
        except Exception:
            logger.exception("learning reflection failed; original run is unaffected")

    async def review(self, task: str, result: HarnessResult) -> LearningReview:
        messages = [
            Message(role="system", content=REVIEWER_SYSTEM_PROMPT),
            Message(role="user", content=_review_prompt(task, result)),
        ]
        chunks: list[str] = []
        async for event in self.registry.stream(
            self.model_id,
            messages,
            tools=[],
            max_output_tokens=self.max_output_tokens,
        ):
            if event.type == "text_delta" and event.delta:
                chunks.append(event.delta)
        payload = "".join(chunks).strip()
        if payload.startswith("```"):
            payload = payload.strip("`").removeprefix("json").strip()
        return LearningReview.model_validate(json.loads(payload))


def _review_prompt(task: str, result: HarnessResult, *, max_chars: int = 3200) -> str:
    lines = [f"Task: {sanitize_task(task)}", f"Final response: {sanitize_text(result.output_text, max_chars=600)}"]
    for message in result.messages:
        if message.role in {"system", "user"}:
            continue
        content = message.content if isinstance(message.content, str) else str(message.content)
        lines.append(f"{message.role}: {sanitize_text(content, max_chars=220)}")
    transcript = "\n".join(lines)
    return transcript[:max_chars]
