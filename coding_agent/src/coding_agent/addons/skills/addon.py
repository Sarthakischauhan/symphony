"""Harness add-on that exposes discovered skills through one on-demand tool."""

from __future__ import annotations

from typing import Any

from core_harness import Addon

from coding_agent.addons.skills.registry import SkillRegistry
from coding_agent.addons.skills.tool import SkillTool


class SkillsAddon(Addon):
    name = "skills"

    def __init__(self, workspace: str, registry: SkillRegistry) -> None:
        self.workspace = workspace
        self.registry = registry

    def attach(self, harness: Any) -> None:
        """Register ``skill`` so bodies load on demand; the prompt keeps a short catalog."""
        if self.registry.skills and SkillTool.name not in harness.tools:
            harness.register_tool(SkillTool(self.workspace, registry=self.registry))


__all__ = ["SkillsAddon"]
