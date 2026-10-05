"""Product harness add-ons.

Each module is one add-on. Feature packages (``compaction``, ``learning``,
``evaluation``, ``langfuse``, ``skills``) keep the machinery; this package is
what ``CodingAgent`` mounts.
"""

from coding_agent.addon.approvals import ApprovalAddon, ApprovalPolicy
from coding_agent.addon.compaction import AiCompactionAddon, ai_compaction_from_config
from coding_agent.addon.evaluation import JevAddon, jev_from_config
from coding_agent.addon.langfuse import LangfuseAddon, langfuse_from_config
from coding_agent.addon.learning import (
    LEARNING_IDLE_DELAY_SECONDS,
    LearningAddon,
    SessionMemoryAddon,
    inject_memory,
    strip_memory_context,
)
from coding_agent.addon.plan import PlanModeAddon, PlanModeState
from coding_agent.addon.skills import SkillsAddon

__all__ = [
    "AiCompactionAddon",
    "ApprovalAddon",
    "ApprovalPolicy",
    "JevAddon",
    "LEARNING_IDLE_DELAY_SECONDS",
    "LangfuseAddon",
    "LearningAddon",
    "PlanModeAddon",
    "PlanModeState",
    "SessionMemoryAddon",
    "SkillsAddon",
    "ai_compaction_from_config",
    "inject_memory",
    "jev_from_config",
    "langfuse_from_config",
    "strip_memory_context",
]
