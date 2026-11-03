"""Validated metadata for local skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from coding_agent.addons.skills.args import ExtensionArg

Invocation = Literal["auto", "manual"]
# on: name, description and path in the catalog. name-only: no description.
# manual: never in the catalog. off: not loaded at all.
SkillMode = Literal["on", "name-only", "manual", "off"]
CATALOG_DESCRIPTION_CHARS = 160


@dataclass(frozen=True)
class SkillSource:
    """A directory of skills and how to label what it holds.

    ``namespace`` prefixes the skill names (``plugin:skill``) so a plugin's skills
    can never collide with, or be shadowed by, a skill of the same name elsewhere.
    """

    origin: str
    path: Path
    namespace: str = ""


@dataclass(frozen=True)
class Skill:
    """A discovered skill and its validated front matter."""

    name: str
    description: str
    path: Path
    origin: str
    invocation: Invocation = "auto"
    args: tuple[ExtensionArg, ...] = ()

    @property
    def root(self) -> Path:
        return self.path.parent


__all__ = ["CATALOG_DESCRIPTION_CHARS", "Invocation", "Skill", "SkillMode", "SkillSource"]
