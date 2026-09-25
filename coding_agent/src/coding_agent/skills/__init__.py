"""Local skill discovery and resource access."""

from coding_agent.skills.addon import SkillsAddon
from coding_agent.skills.models import Skill, SkillDiagnostic
from coding_agent.skills.registry import SkillRegistry, bundled_skills_root

__all__ = ["Skill", "SkillDiagnostic", "SkillRegistry", "SkillsAddon", "bundled_skills_root"]
