"""Harness add-on that mounts model-backed compaction."""

from __future__ import annotations

from typing import Any, Optional

from core_harness.addons import Addon
from core_harness.addons.compaction import KeepSystemRecentCompactor
from core_harness.config import HarnessConfig
from core_harness.context.compact import DEFAULT_PRUNE_KEEP_RECENT

from coding_agent.compaction.summarizer import (
    DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS,
    DEFAULT_TRANSCRIPT_MAX_CHARS,
    ModelTurnSummarizer,
)
from coding_agent.config import CompactionConfig


class AiCompactionAddon(Addon):
    """Mount a ``KeepSystemRecentCompactor`` whose summary is written by the model.

    Keep/drop stays the harness policy (system prompt, pinned first task,
    atomic assistant/tool groups, recent window). This add-on only supplies the
    ``TurnSummarizer`` that turns the dropped turns into one compacted-context
    message, using the harness registry and its *current* ``model_id`` so the
    summary follows ``/model`` switches.

    It occupies the ``compaction`` add-on slot, so it replaces the harness
    ``CompactionAddon`` rather than sitting beside it. Children fork a fresh
    add-on with the same settings, matching ``CompactionAddon``; the child then
    binds the summarizer to its own registry and model.
    """

    name = "compaction"

    def __init__(
        self,
        *,
        keep_recent: int = 10,
        target_tokens: Optional[int] = None,
        keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
        max_output_tokens: int = DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS,
        max_transcript_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS,
        model_id: Optional[str] = None,
    ) -> None:
        self.keep_recent = keep_recent
        self.target_tokens = target_tokens
        self.keep_recent_tool_results = keep_recent_tool_results
        self.max_output_tokens = max_output_tokens
        self.max_transcript_chars = max_transcript_chars
        self.model_id = model_id
        self.summarizer: Optional[ModelTurnSummarizer] = None
        self.compactor: Optional[KeepSystemRecentCompactor] = None

    def attach(self, harness: Any) -> None:
        self.summarizer = ModelTurnSummarizer(
            registry=harness.registry,
            model_id=self.model_id or (lambda: str(harness.model_id)),
            max_output_tokens=self.max_output_tokens,
            max_transcript_chars=self.max_transcript_chars,
        )
        self.compactor = KeepSystemRecentCompactor(
            keep_recent=self.keep_recent,
            target_tokens=self.target_tokens,
            keep_recent_tool_results=self.keep_recent_tool_results,
            summarizer=self.summarizer,
        )
        harness.state.compactor = self.compactor

    def fork_for_child(self, parent_harness: Any) -> AiCompactionAddon:
        """Fresh add-on with the same settings; binds to the child on attach."""
        del parent_harness
        return AiCompactionAddon(
            keep_recent=self.keep_recent,
            target_tokens=self.target_tokens,
            keep_recent_tool_results=self.keep_recent_tool_results,
            max_output_tokens=self.max_output_tokens,
            max_transcript_chars=self.max_transcript_chars,
            model_id=self.model_id,
        )


def ai_compaction_from_config(
    harness_config: HarnessConfig,
    compaction: CompactionConfig,
) -> AiCompactionAddon:
    """Build the model-backed add-on from harness limits plus summary settings."""
    return AiCompactionAddon(
        keep_recent=harness_config.compaction_keep_recent,
        target_tokens=harness_config.context_target_tokens,
        keep_recent_tool_results=harness_config.tool_result_keep_recent,
        max_output_tokens=compaction.max_output_tokens,
        max_transcript_chars=compaction.max_transcript_chars,
    )


__all__ = ["AiCompactionAddon", "ai_compaction_from_config"]
