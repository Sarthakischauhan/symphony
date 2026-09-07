"""Local skill discovery and resource access."""

from coding_agent.skills.addon import SkillsAddon
from coding_agent.skills.models import Skill, SkillDiagnostic
from coding_agent.skills.registry import SkillRegistry

__all__ = ["Skill", "SkillDiagnostic", "SkillRegistry", "SkillsAddon"]
