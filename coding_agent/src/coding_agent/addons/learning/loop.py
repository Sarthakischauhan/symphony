"""Durable capture queue with one non-blocking, serialized extraction worker."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from core_ai.models import get_model
from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent.config import LearningConfig
from coding_agent.addons.learning.prompts import CAPTURE_SYSTEM_PROMPT
from coding_agent.addons.learning.sanitize import sanitize_task, sanitize_text
from core_ai.content import text_from_content
from coding_agent.addons.learning.store import MAX_CAPTURE_ATTEMPTS, LearningStore

logger = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, object]], Awaitable[None]]


class Observation(BaseModel):
    """Extraction cannot grant global scope or mutate existing memory."""

    text: str = Field(min_length=1, max_length=600)
    topic: str = Field(min_length=1, max_length=120)
    scope: Literal["workspace"] = "workspace"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    model_config = {"extra": "forbid"}

    @field_validator("topic")
    @classmethod
    def topic_id(cls, value: str) -> str:
        value = re.sub(r"[^a-z0-9_-]+", "-", sanitize_text(value, max_chars=120).casefold()).strip("-_")
        if not value:
            raise ValueError("topic requires an identifier")
        return value

    @field_validator("text")
    @classmethod
    def clean(cls, value: str) -> str:
        value = sanitize_text(value, max_chars=600).strip()
        if not value:
            raise ValueError("observation fields must not be blank")
        return value


class LearningReview(BaseModel):
    """Structured capture response; kept exported for import compatibility."""

    observations: list[Observation] = Field(default_factory=list, max_length=8)
    transcript_summary: str = Field(default="", max_length=400)
    model_config = {"extra": "forbid"}


def two_line_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(sanitize_text(line, max_chars=140) for line in lines[:2])


_THINKING_ORDER = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def _capture_effort(model_id: str) -> str | None:
    """Lowest reasoning effort the catalog advertises for ``model_id``.

    Extraction is a small structured task; reasoning only competes with the
    JSON for output tokens. Unknown models keep the provider default.
    """
    provider, _, name = model_id.partition(":")
    model = get_model(provider, name)
    levels = dict(model.thinking_level_map) if model is not None else {}
    return next((levels[level] for level in _THINKING_ORDER if levels.get(level)), None)


def _capture_messages(messages: list[Message] | list[dict]) -> list[dict]:
    """Bound and sanitize evidence before it reaches disk or another model."""
    result = []
    remaining = 64000
    for message in messages[-64:]:
        raw = message if isinstance(message, dict) else message.model_dump(mode="json")
        role = str(raw.get("role", "unknown"))[:32]
        if role == "system":
            continue
        content = raw.get("content", "")
        if not isinstance(content, str):
            content = text_from_content(content)
        content = sanitize_text(content, max_chars=min(8000, remaining))
        result.append({"role": role, "content": content})
        remaining -= len(content)
        if remaining < 4:
            break
    return result


class LearningLoop:
    def __init__(
        self, store: LearningStore, *, registry: ModelRegistry, model_id: str,
        max_output_tokens: int = LearningConfig().max_output_tokens,
        context_limit: int = LearningConfig().context_limit,
        context_max_chars: int = LearningConfig().context_max_chars,
    ) -> None:
        self.store = store
        self.registry = registry
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self.context_limit = context_limit
        self.context_max_chars = context_max_chars
        self._worker: asyncio.Task[None] | None = None
        self._recaps: dict[str, Emit] = {}
        # Control-plane emit for capture notices; bound by ``LearningAddon``.
        self.emit: Emit | None = None

    def capture(self, task: str, messages: list[Message] | list[dict]) -> str:
        """Persist synchronously BEFORE spawning; later turns never cancel this job."""
        job_id = self.store.enqueue_capture(
            sanitize_task(task), _capture_messages(messages), self.store.session_id,
        )
        self.resume()
        return job_id

    def resume(self) -> None:
        """Resume durable pending jobs before a run (also safe outside an event loop)."""
        if self._worker is not None and not self._worker.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._worker = loop.create_task(self._drain())

    def schedule(
        self, task: str, result: HarnessResult, *, emit: Emit | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        """Compatibility wrapper; idle debounce is intentionally no longer used."""
        del delay_seconds
        job_id = self.capture(task, result.messages)
        if emit is not None:
            self._recaps[job_id] = emit

    def cancel(self) -> None:
        """Cancel execution only: all unfinished jobs remain durable."""
        if self._worker is not None:
            self._worker.cancel()

    async def wait(self) -> None:
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)

    async def shutdown(self) -> None:
        self.cancel()
        await self.wait()
        self._recaps.clear()

    async def _drain(self) -> None:
        try:
            self.store.consolidate()
        except (OSError, ValueError):
            logger.exception("memory consolidation deferred")
        attempted: set[str] = set()
        while True:
            jobs = [job for job in self.store.pending_jobs() if job["id"] not in attempted]
            if not jobs:
                return
            for job in jobs:
                job_id = job["id"]
                attempted.add(job_id)
                try:
                    review = await self._extract(job)
                    self.store.complete_job(job_id, [item.model_dump() for item in review.observations if item.confidence >= 0.7])
                    self.store.consolidate()
                except asyncio.CancelledError:
                    raise
                except ValueError as exc:
                    # Empty, unparseable, or invalid output: count it so a job
                    # that keeps producing bad output stops being retried.
                    await self._bad_output(job_id, exc)
                    continue
                except Exception:
                    logger.exception("memory capture failed; pending job will retry next run")
                    continue
                emit = self._recaps.pop(job_id, None)
                recap = two_line_summary(review.transcript_summary)
                if emit is not None and recap:
                    try:
                        await emit("run_summary", {"label": "summary so far", "summary": recap})
                    except Exception:
                        logger.exception("memory recap delivery failed")

    async def _bad_output(self, job_id: str, error: ValueError) -> None:
        try:
            failed = self.store.record_capture_failure(job_id, error)
        except (OSError, ValueError):
            logger.exception("memory capture failure could not be recorded")
            return
        state = (f"gave up after {MAX_CAPTURE_ATTEMPTS} attempts; job marked failed" if failed
                 else "will retry next run")
        logger.warning("memory capture returned no usable output for job %s (%s): %s",
                       job_id[:12], state, error)
        if self.emit is None:
            return
        try:
            await self.emit("run_summary", {
                "label": "memory capture",
                "summary": sanitize_text(f"Memory capture got no usable output ({state}): {error}",
                                         max_chars=280),
            })
        except Exception:
            logger.exception("memory capture notice delivery failed")

    async def _extract(self, job: dict) -> LearningReview:
        evidence = json.dumps({"task": sanitize_task(job["task"]),
                               "messages": _capture_messages(job["messages"])}, ensure_ascii=False)
        self.store.archive_context("capture", job["task"], evidence)
        messages = [Message(role="system", content=CAPTURE_SYSTEM_PROMPT),
                    Message(role="user", content=evidence)]
        chunks: list[str] = []
        size = 0
        async for event in self.registry.stream(
            self.model_id, messages, tools=[], max_output_tokens=self.max_output_tokens,
            reasoning_effort=_capture_effort(self.model_id),
        ):
            if event.type == "retry" and event.retry_resets_stream:
                # The provider restarts the response; keep only the new attempt.
                chunks.clear()
                size = 0
            elif event.type == "text_delta" and event.delta:
                size += len(event.delta)
                if size > 16000:
                    raise ValueError("capture response exceeds bound")
                chunks.append(event.delta)
        payload = "".join(chunks).strip()
        if not payload:
            raise ValueError("capture response contained no text")
        if payload.startswith("```"):
            payload = payload.strip("`").removeprefix("json").strip()
        decoded = json.loads(payload)
        # A bare empty list is the preferred no-evidence response.
        if isinstance(decoded, list):
            decoded = {"observations": decoded}
        return LearningReview.model_validate(decoded)
