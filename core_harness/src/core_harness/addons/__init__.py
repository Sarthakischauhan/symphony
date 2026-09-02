"""Opt-in harness add-ons.

``CoreHarness`` is an extension surface. Pass ``addons=[...]`` at construction
or call ``register_addon``. There is no directory discovery and no skill
loader; skills can hang off this same attach path later.
"""

from __future__ import annotations

from core_harness.addons.addon import Addon, AddonProtocol
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
from core_harness.addons.subagent import ChildConfig, ChildIdentity, SubagentAddon
from core_harness.addons.telemetry import (
    NullTelemetry,
    Telemetry,
    TelemetryAddon,
)


__all__ = [
    "Addon",
    "AddonProtocol",
    "Checkpoint",
    "CheckpointStatus",
    "ChildConfig",
    "ChildIdentity",
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
