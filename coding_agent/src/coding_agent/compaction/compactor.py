"""``InferenceCompactor``: harness keep/drop plan, model-written summary."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Union

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness.addons.compaction import (
    KeepDropPlan,
    compaction_target,
    fit_to_target,
    plan_keep_drop,
)
from core_harness.context.compact import DEFAULT_PRUNE_KEEP_RECENT

from coding_agent.compaction.prompts import COMPACTION_SYSTEM_PROMPT
from coding_agent.compaction.transcript import (
    DEFAULT_TRANSCRIPT_MAX_CHARS,
    build_compacted_message,
    render_dropped_turns,
)

logger = logging.getLogger(__name__)

ModelIdSource = Union[str, Callable[[], str]]

DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS = 700


class InferenceCompactor:
    """``Compactor`` that summarises dropped history with one model call.

    Keep/drop is the harness rule (``plan_keep_drop``): system prompt, pinned
    first user task, atomic assistant/tool groups, recent window, token target.
    The dropped slice is rendered to a bounded transcript and sent to the
    active model exactly once; the reply becomes the single
    ``COMPACTED_CONTEXT_MARK`` user message that replaces that slice. When the
    provider fails or returns nothing, the harness template summary is used
    for the same slice so a compact never leaves the conversation broken.

    ``model_id`` may be a callable so the summary follows ``/model`` switches.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: ModelIdSource,
        keep_recent: int = 10,
        target_tokens: Optional[int] = None,
        keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
        max_output_tokens: int = DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS,
        max_transcript_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS,
    ) -> None:
        if keep_recent < 1:
            raise ValueError("keep_recent must be >= 1")
        if target_tokens is not None and target_tokens < 1:
            raise ValueError("target_tokens must be positive or None")
        if keep_recent_tool_results < 0:
            raise ValueError("keep_recent_tool_results must be >= 0")
        self.registry = registry
        self._model_id = model_id
        self.keep_recent = keep_recent
        self.target_tokens = target_tokens
        self.keep_recent_tool_results = keep_recent_tool_results
        self.max_output_tokens = max_output_tokens
        self.max_transcript_chars = max_transcript_chars

    @property
    def model_id(self) -> str:
        source = self._model_id
        return source() if callable(source) else source

    def plan(self, messages: List[Message], *, context_limit: Optional[int]) -> KeepDropPlan:
        return plan_keep_drop(
            messages,
            keep_recent=self.keep_recent,
            target_tokens=self.target_tokens,
            context_limit=context_limit,
        )

    async def compact(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
    ) -> List[Message]:
        del turn, tokens_used, context_left
        plan = self.plan(messages, context_limit=context_limit)
        summary = await self.summarize(plan) if plan.dropped else None
        return fit_to_target(
            plan.assemble(summary),
            target=compaction_target(self.target_tokens, context_limit),
            keep_recent_tool_results=self.keep_recent_tool_results,
        )

    async def summarize(self, plan: KeepDropPlan) -> Message:
        """One compacted-context message for ``plan.dropped``; template on failure."""
        transcript = render_dropped_turns(plan.dropped, max_chars=self.max_transcript_chars)
        try:
            narrative = await self.narrate(transcript)
        except Exception:  # noqa: BLE001
            logger.warning(
                "model compaction summary failed; using template summary", exc_info=True
            )
            narrative = ""
        if not narrative.strip():
            template = plan.template_summary()
            assert template is not None
            return template
        return build_compacted_message(
            plan.dropped, narrative=narrative, tokens=plan.dropped_tokens
        )

    async def narrate(self, transcript: str) -> str:
        """One tool-free model call that returns the summary text."""
        messages = [
            Message(role="system", content=COMPACTION_SYSTEM_PROMPT),
            Message(
                role="user",
                content=(
                    "Transcript turns being removed from context:\n\n"
                    f"{transcript}\n\n"
                    "Write the handoff summary."
                ),
            ),
        ]
        chunks: List[str] = []
        async for event in self.registry.stream(
            self.model_id,
            messages,
            tools=[],
            max_output_tokens=self.max_output_tokens,
        ):
            if event.type == "text_delta" and event.delta:
                chunks.append(event.delta)
        return "".join(chunks).strip()


__all__ = [
    "DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS",
    "InferenceCompactor",
    "ModelIdSource",
]
