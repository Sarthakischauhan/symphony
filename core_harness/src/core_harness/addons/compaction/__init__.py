"""Compaction add-on: mount a ``Compactor`` onto the harness."""

from __future__ import annotations

from typing import Any, Optional

from core_harness.addons.addon import Addon
from core_harness.addons.compaction.policy import (
    COMPACTION_CONTINUATION,
    Compactor,
    KeepDropPlan,
    KeepSystemRecentCompactor,
    compaction_header,
    compaction_target,
    dropped_turn_facts,
    plan_keep_drop,
    summarize_dropped_turns,
)
from core_harness.config import HarnessConfig


class CompactionAddon(Addon):
    """Mount a ``Compactor`` onto ``CoreHarness.state``."""

    name = "compaction"

    def __init__(
        self,
        compactor: Compactor | None = None,
        *,
        keep_recent_tools: int = 32,
        target_tokens: Optional[int] = None,
    ) -> None:
        self.compactor = compactor or KeepSystemRecentCompactor(
            keep_recent_tools=keep_recent_tools,
            target_tokens=target_tokens,
        )
        if isinstance(self.compactor, KeepSystemRecentCompactor):
            keep_recent_tools = self.compactor.keep_recent_tools
            target_tokens = self.compactor.target_tokens
        self.keep_recent_tools = keep_recent_tools
        self.target_tokens = target_tokens

    def attach(self, harness: Any) -> None:
        harness.state.compactor = self.compactor

    def fork_for_child(self, parent_harness: Any) -> CompactionAddon:
        """New add-on with a fresh compactor using the same settings."""
        del parent_harness
        return CompactionAddon(
            keep_recent_tools=self.keep_recent_tools,
            target_tokens=self.target_tokens,
        )


def compaction_from_config(config: HarnessConfig) -> CompactionAddon:
    """Build the keep-system-recent add-on from harness settings."""
    return CompactionAddon(
        keep_recent_tools=config.compaction_keep_recent_tools,
        target_tokens=config.context_target_tokens,
    )


__all__ = [
    "COMPACTION_CONTINUATION",
    "CompactionAddon",
    "Compactor",
    "KeepDropPlan",
    "KeepSystemRecentCompactor",
    "compaction_from_config",
    "compaction_header",
    "compaction_target",
    "dropped_turn_facts",
    "plan_keep_drop",
    "summarize_dropped_turns",
]
