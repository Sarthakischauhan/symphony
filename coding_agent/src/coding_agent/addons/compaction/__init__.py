"""Model-backed conversation compaction for the coding agent.

The harness owns the ``Compactor`` protocol and the keep/drop rule
(``plan_keep_drop``). ``InferenceCompactor`` implements that protocol and
writes the compacted-context message with the active model. The add-on that
mounts it lives in ``coding_agent.addons.compaction.addon`` so this package does not
import the add-on layer while it is still loading.
"""

from __future__ import annotations

from typing import Any

from coding_agent._lazy import resolve
from coding_agent.addons.compaction.compactor import InferenceCompactor
from coding_agent.addons.compaction.transcript import (
    build_compacted_message,
    render_dropped_turns,
)

_ADDON_EXPORTS = {
    "AiCompactionAddon": ("coding_agent.addons.compaction.addon", "AiCompactionAddon"),
    "ai_compaction_from_config": ("coding_agent.addons.compaction.addon", "ai_compaction_from_config"),
}

__all__ = [
    "AiCompactionAddon",
    "InferenceCompactor",
    "ai_compaction_from_config",
    "build_compacted_message",
    "render_dropped_turns",
]


def __getattr__(name: str) -> Any:
    return resolve(globals(), name, _ADDON_EXPORTS)
