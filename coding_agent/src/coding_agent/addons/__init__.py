"""Product harness add-ons.

Feature packages keep each add-on's hooks and supporting machinery together.
This package exports the add-ons that ``CodingAgent`` mounts.
"""

from coding_agent.addons.approvals import ApprovalAddon, ApprovalPolicy
from coding_agent.addons.compaction.addon import AiCompactionAddon, ai_compaction_from_config
from coding_agent.addons.evaluation.addon import JevAddon, jev_from_config
from coding_agent.addons.langfuse.addon import LangfuseAddon, langfuse_from_config
from coding_agent.addons.learning.addon import (
    LEARNING_IDLE_DELAY_SECONDS,
    LearningAddon,
    SessionMemoryAddon,
    inject_memory,
    strip_memory_context,
)
from coding_agent.addons.plan.addon import PlanModeAddon, PlanModeState
from coding_agent.addons.skills.addon import SkillsAddon

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
