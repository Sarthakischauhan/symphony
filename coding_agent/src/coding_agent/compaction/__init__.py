"""Model-backed conversation compaction for the coding agent.

The harness owns the ``Compactor`` protocol and the keep/drop rule
(``plan_keep_drop``). ``InferenceCompactor`` implements that protocol on top
of the same rule and writes the compacted-context message with the active
model; ``AiCompactionAddon`` mounts it on the harness so both auto-compaction
(before each model turn) and ``/compact`` run through it. coding_agent never
mounts the harness template compactor.
"""

from coding_agent.compaction.addon import AiCompactionAddon, ai_compaction_from_config
from coding_agent.compaction.compactor import InferenceCompactor
from coding_agent.compaction.transcript import (
    build_compacted_message,
    render_dropped_turns,
)

__all__ = [
    "AiCompactionAddon",
    "InferenceCompactor",
    "ai_compaction_from_config",
    "build_compacted_message",
    "render_dropped_turns",
]
