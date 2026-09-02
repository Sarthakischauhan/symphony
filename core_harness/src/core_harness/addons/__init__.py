"""Opt-in harness add-ons.

``CoreHarness`` is an extension surface. Pass ``addons=[...]`` at construction
or call ``register_addon``. There is no directory discovery and no skill
loader; skills can hang off this same attach path later.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core_harness.addons.compaction import (
    CompactionAddon,
    Compactor,
    KeepSystemRecentCompactor,
    compaction_from_config,
)
from core_harness.addons.persistence import (
    Checkpoint,
    CheckpointStatus,
    NullPersistence,
    Persistence,
    PersistenceAddon,
)
from core_harness.addons.subagent import ChildConfig, SubagentAddon
from core_harness.addons.telemetry import (
    NullTelemetry,
    Telemetry,
    TelemetryAddon,
)


@runtime_checkable
class Addon(Protocol):
    """Tiny attach protocol. Optional hooks: before_turn, after_turn, on_tool, on_compact."""

    name: str

    def attach(self, harness: Any) -> None:
        """Mount this add-on onto a harness. Called once from ``register_addon``."""
        ...


__all__ = [
    "Addon",
    "Checkpoint",
    "CheckpointStatus",
    "ChildConfig",
    "CompactionAddon",
    "Compactor",
    "KeepSystemRecentCompactor",
    "NullPersistence",
    "NullTelemetry",
    "Persistence",
    "PersistenceAddon",
    "SubagentAddon",
    "Telemetry",
    "TelemetryAddon",
    "compaction_from_config",
]
