"""Compaction add-on: mount a ``Compactor`` onto the harness."""

from __future__ import annotations

from typing import Any, Optional

from core_harness.addons.compaction.policy import Compactor, KeepSystemRecentCompactor
from core_harness.config import HarnessConfig
from core_harness.context.compact import DEFAULT_PRUNE_KEEP_RECENT


class CompactionAddon:
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

    def attach(self, harness: Any) -> None:
        harness.state.compactor = self.compactor


def compaction_from_config(config: HarnessConfig) -> CompactionAddon:
    """Build the keep-system-recent add-on from harness settings."""
    return CompactionAddon(
        keep_recent=config.compaction_keep_recent,
        target_tokens=config.context_target_tokens,
        keep_recent_tool_results=config.tool_result_keep_recent,
    )


__all__ = [
    "CompactionAddon",
    "Compactor",
    "KeepSystemRecentCompactor",
    "compaction_from_config",
]
