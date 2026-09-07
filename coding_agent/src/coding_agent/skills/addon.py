"""Harness add-on that exposes discovered skills as ordinary product tools."""

from __future__ import annotations

from typing import Any

from core_harness import Addon

from coding_agent.skills.registry import SkillRegistry


class SkillsAddon(Addon):
    name = "skills"

    def __init__(self, workspace: str, registry: SkillRegistry) -> None:
        self.workspace = workspace
        self.registry = registry

    def attach(self, harness: Any) -> None:
        del harness


__all__ = ["SkillsAddon"]
