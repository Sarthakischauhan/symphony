"""Local skill discovery and resource access."""

from __future__ import annotations

from typing import Any

from coding_agent._lazy import resolve
from coding_agent.addons.skills.args import ExtensionArg, render_args
from coding_agent.addons.skills.models import Skill, SkillDiagnostic
from coding_agent.addons.skills.registry import SkillRegistry, bundled_skills_root

_ADDON_EXPORTS = {
    "SkillsAddon": ("coding_agent.addons.skills.addon", "SkillsAddon"),
}

__all__ = [
    "ExtensionArg",
    "Skill",
    "SkillDiagnostic",
    "SkillRegistry",
    "SkillsAddon",
    "bundled_skills_root",
    "render_args",
]


def __getattr__(name: str) -> Any:
    return resolve(globals(), name, _ADDON_EXPORTS)
