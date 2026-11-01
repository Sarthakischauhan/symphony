"""Skills: discovery, the prompt catalog, and (``install``) adding and removing them."""

from coding_agent.addons.skills.args import ExtensionArg, render_args
from coding_agent.addons.skills.catalog import CatalogEntry, SkillCatalog, build_catalog
from coding_agent.addons.skills.discovery import SkillSet, discover_skills
from coding_agent.addons.skills.models import Skill, SkillMode, SkillSource
from coding_agent.addons.skills.registry import SkillRegistry

__all__ = [
    "CatalogEntry",
    "ExtensionArg",
    "Skill",
    "SkillCatalog",
    "SkillMode",
    "SkillRegistry",
    "SkillSet",
    "SkillSource",
    "build_catalog",
    "discover_skills",
    "render_args",
]
