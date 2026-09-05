"""Compaction add-on: mount a ``Compactor`` onto the harness."""

from __future__ import annotations

from typing import Any, Optional

from core_harness.addons.addon import Addon
from core_harness.addons.compaction.policy import (
    COMPACTION_CONTINUATION,
    Compactor,
    KeepSystemRecentCompactor,
    TemplateTurnSummarizer,
    TurnSummarizer,
    compaction_header,
    dropped_turn_facts,
    summarize_dropped_turns,
)
from core_harness.config import HarnessConfig
from core_harness.context.compact import DEFAULT_PRUNE_KEEP_RECENT


class CompactionAddon(Addon):
    """Mount a ``Compactor`` onto ``CoreHarness.state``."""

    name = "compaction"

    def __init__(
        self,
        compactor: Compactor | None = None,
        *,
        keep_recent: int = 10,
        target_tokens: Optional[int] = None,
        keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
    ) -> None:
        self.compactor = compactor or KeepSystemRecentCompactor(
            keep_recent=keep_recent,
            target_tokens=target_tokens,
            keep_recent_tool_results=keep_recent_tool_results,
        )
        if isinstance(self.compactor, KeepSystemRecentCompactor):
            keep_recent = self.compactor.keep_recent
            target_tokens = self.compactor.target_tokens
            keep_recent_tool_results = self.compactor.keep_recent_tool_results
        self.keep_recent = keep_recent
        self.target_tokens = target_tokens
        self.keep_recent_tool_results = keep_recent_tool_results

    def attach(self, harness: Any) -> None:
        harness.state.compactor = self.compactor

    def fork_for_child(self, parent_harness: Any) -> CompactionAddon:
        """New add-on with a fresh compactor using the same settings."""
        del parent_harness
        if isinstance(self.compactor, KeepSystemRecentCompactor):
            return CompactionAddon(
                KeepSystemRecentCompactor(
                    keep_recent=self.compactor.keep_recent,
                    target_tokens=self.compactor.target_tokens,
                    keep_recent_tool_results=self.compactor.keep_recent_tool_results,
                    summarizer=self.compactor.summarizer,
                )
            )
        return CompactionAddon(
            keep_recent=self.keep_recent,
            target_tokens=self.target_tokens,
            keep_recent_tool_results=self.keep_recent_tool_results,
        )


def compaction_from_config(config: HarnessConfig) -> CompactionAddon:
    """Build the keep-system-recent add-on from harness settings."""
    return CompactionAddon(
        keep_recent=config.compaction_keep_recent,
        target_tokens=config.context_target_tokens,
        keep_recent_tool_results=config.tool_result_keep_recent,
    )


__all__ = [
    "COMPACTION_CONTINUATION",
    "CompactionAddon",
    "Compactor",
    "KeepSystemRecentCompactor",
    "TemplateTurnSummarizer",
    "TurnSummarizer",
    "compaction_from_config",
    "compaction_header",
    "dropped_turn_facts",
    "summarize_dropped_turns",
]
