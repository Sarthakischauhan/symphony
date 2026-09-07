"""Validated metadata for local skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    """A discovered skill and its validated front matter."""

    skill_id: str
    name: str
    description: str
    root: Path
    origin: str
    body: str

    @property
    def resources(self) -> tuple[str, ...]:
        paths: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                relative = path.relative_to(self.root)
                path.resolve().relative_to(self.root.resolve())
            except ValueError:
                continue
            if relative.name == "SKILL.md":
                continue
            if relative.parts and relative.parts[0] in {"references", "scripts", "assets"}:
                paths.append(relative.as_posix())
        return tuple(paths)


@dataclass(frozen=True)
class SkillDiagnostic:
    """A bounded, user-facing discovery diagnostic."""

    source: str
    message: str


__all__ = ["Skill", "SkillDiagnostic"]
