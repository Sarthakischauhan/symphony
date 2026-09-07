"""Opt-in harness add-ons.

``CoreHarness`` is an extension surface. Pass ``addons=[...]`` at construction
or call ``register_addon``. There is no directory discovery and no skill
loader; skills can hang off this same attach path later.
"""

from __future__ import annotations

from core_harness.addons.addon import Addon
from core_harness.addons.compaction import (
    CompactionAddon,
    Compactor,
    KeepDropPlan,
    KeepSystemRecentCompactor,
    compaction_from_config,
    plan_keep_drop,
)
from core_harness.addons.persistence import (
    Checkpoint,
    CheckpointStatus,
    NullPersistence,
    Persistence,
    PersistenceAddon,
)
from core_harness.addons.subagent import ChildConfig, ChildIdentity, SubagentAddon


__all__ = [
    "Addon",
    "Checkpoint",
    "CheckpointStatus",
    "ChildConfig",
    "ChildIdentity",
    "CompactionAddon",
    "Compactor",
    "KeepDropPlan",
    "KeepSystemRecentCompactor",
    "NullPersistence",
    "Persistence",
    "PersistenceAddon",
    "SubagentAddon",
    "compaction_from_config",
    "plan_keep_drop",
]
