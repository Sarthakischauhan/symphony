"""Validated metadata for local skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillArg:
    """One argument declared in skill or plugin front matter."""

    name: str
    type: str
    description: str
    required: bool = False
    default: str | int | float | bool | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skill:
    """A discovered skill and its validated front matter."""

    skill_id: str
    name: str
    description: str
    root: Path
    origin: str
    body: str
    args: tuple[SkillArg, ...] = ()

    def catalog_line(self) -> str:
        """One prompt line: id, description, path, and the loaded args."""
        line = (
            f"- {self.skill_id}: {self.description} "
            f"(SKILL.md: {self.root / 'SKILL.md'})"
        )
        if not self.args:
            return line
        rendered = ", ".join(
            f"{arg.name}: {arg.type}" + (" required" if arg.required else "")
            for arg in self.args
        )
        return f"{line} [args: {rendered}]"

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


__all__ = ["Skill", "SkillArg", "SkillDiagnostic"]
