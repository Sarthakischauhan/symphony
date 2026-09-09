"""Non-blocking post-run reflection using one structured model call."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent.config import LearningConfig
from coding_agent.learning.prompts import REVIEWER_SYSTEM_PROMPT
from coding_agent.learning.sanitize import sanitize_task, sanitize_text
from coding_agent.learning.store import LearningStore

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, object]], Awaitable[None]]


class MemoryOp(BaseModel):
    action: str = "add"
    text: str = ""
    match: str = ""

    model_config = {"extra": "ignore"}


class LearningReview(BaseModel):
    memory_ops: list[MemoryOp] = Field(default_factory=list)
    # Legacy fields are accepted for compatibility but are no longer acted on.
    should_save: bool = False
    summary: str = ""
    transcript_summary: str = ""
    worked: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    applicable_when: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def two_line_summary(text: str) -> str:
    """Clamp a recap to two short lines for the agent transcript."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    cleaned = [sanitize_text(line, max_chars=140) for line in lines[:2]]
    return "\n".join(line for line in cleaned if line)


class LearningLoop:
    def __init__(
        self,
        store: LearningStore,
        *,
        registry: ModelRegistry,
        model_id: str,
        max_output_tokens: int = LearningConfig().max_output_tokens,
        context_limit: int = LearningConfig().context_limit,
        context_max_chars: int = LearningConfig().context_max_chars,
    ) -> None:
        self.store = store
        self.context_limit = context_limit
        self.context_max_chars = context_max_chars
        self.registry = registry
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(
        self,
        task: str,
        result: HarnessResult,
        *,
        emit: Optional[Emit] = None,
    ) -> None:
        """Start reflection after a completed run without delaying its result."""
        background = asyncio.create_task(self._review_and_store(task, result, emit=emit))
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

    async def _review_and_store(
        self,
        task: str,
        result: HarnessResult,
        *,
        emit: Optional[Emit] = None,
    ) -> None:
        try:
            review = await self.review(task, result)
            recap = two_line_summary(review.transcript_summary)
            if recap and emit is not None:
                await emit(
                    "run_summary",
                    {"label": "summary so far", "summary": recap},
                )
            for op in review.memory_ops[:4]:
                action = op.action.strip().lower()
                if action == "add" and op.text.strip():
                    self.store.memory_operation("add", text=op.text)
                elif action == "replace" and op.text.strip() and op.match.strip():
                    self.store.memory_operation(action, text=op.text, match=op.match)
                elif action == "remove" and op.match.strip():
                    self.store.memory_operation(action, text=op.text, match=op.match)
            # Backward-compatible reviewers may still return the legacy fields;
            # convert that proposal into the new bounded memory file.
            if not review.memory_ops and review.should_save and review.summary.strip():
                self.store.memory_operation("add", text=review.summary)
                # Keep the legacy archive populated for existing consumers while
                # the markdown file is the only injected prompt source.
                self.store.append_legacy_summary(review.summary, source_task=task)
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
