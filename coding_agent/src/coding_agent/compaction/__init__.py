"""Model-backed conversation compaction for the coding agent.

The harness owns the ``Compactor`` protocol and the keep/drop policy
(``KeepSystemRecentCompactor``). This package supplies the summarizer that
writes the compacted-context message with the active model, and the add-on
that mounts it on the harness.
"""

from coding_agent.compaction.addon import AiCompactionAddon, ai_compaction_from_config
from coding_agent.compaction.summarizer import (
    ModelTurnSummarizer,
    build_compacted_message,
    render_dropped_turns,
)

__all__ = [
    "AiCompactionAddon",
    "ModelTurnSummarizer",
    "ai_compaction_from_config",
    "build_compacted_message",
    "render_dropped_turns",
]
