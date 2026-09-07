"""Safe discovery and bounded access to local Markdown skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coding_agent.skills.models import Skill, SkillDiagnostic

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_FILE_BYTES = 128_000
_MAX_FIELD_CHARS = 1_000


class _FrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_FIELD_CHARS)
    description: str = Field(min_length=1, max_length=_MAX_FIELD_CHARS)


class SkillRegistry:
    """Discover skills and expose only paths within their skill roots."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills = {skill.skill_id: skill for skill in skills}

    @property
    def skills(self) -> tuple[Skill, ...]:
        return tuple(sorted(self._skills.values(), key=lambda skill: skill.skill_id))

    def get(self, skill_id: str) -> Skill:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise ValueError(f"Unknown skill id: {skill_id}") from exc

    def resource_path(self, skill_id: str, relative_path: str) -> Path:
        skill = self.get(skill_id)
        candidate = Path(relative_path)
        if candidate.is_absolute() or not relative_path or "" in candidate.parts:
            raise ValueError("resource path must be relative")
        original = skill.root / candidate
        resolved = original.resolve()
        if not resolved.is_relative_to(skill.root.resolve()):
            raise ValueError("resource path escapes the skill")
        if any(part.is_symlink() for part in _parents_from(skill.root, original)):
            raise ValueError("symlink skill resources are not supported")
        if not resolved.is_file():
            raise ValueError(f"Skill resource not found: {relative_path}")
        return resolved

    @classmethod
    def discover(
        cls,
        roots: Iterable[tuple[str, Path]],
        *,
        max_skills: int = 100,
    ) -> tuple["SkillRegistry", tuple[SkillDiagnostic, ...]]:
        found: list[Skill] = []
        diagnostics: list[SkillDiagnostic] = []
        seen: set[str] = set()
        for origin, root in roots:
            root = root.expanduser().resolve()
            if not root.is_dir():
                continue
            candidates = [root] if (root / "SKILL.md").is_file() else sorted(
                path for path in root.iterdir() if path.is_dir()
            )
            for skill_root in candidates:
                document = skill_root / "SKILL.md"
                if not document.is_file():
                    continue
                try:
                    skill = _parse_skill(origin, skill_root, document)
                    if skill.skill_id in seen:
                        raise ValueError(f"duplicate skill id: {skill.skill_id}")
                    seen.add(skill.skill_id)
                    if len(found) >= max_skills:
                        diagnostics.append(SkillDiagnostic(str(document), "skill limit reached"))
                        continue
                    found.append(skill)
                except (OSError, UnicodeError, ValueError, ValidationError) as exc:
                    diagnostics.append(SkillDiagnostic(str(document), str(exc)))
        return cls(found), tuple(diagnostics)


def _parents_from(root: Path, path: Path) -> list[Path]:
    current = root
    parents: list[Path] = []
    for part in path.relative_to(root).parts:
        current = current / part
        parents.append(current)
    return parents


def _parse_skill(origin: str, root: Path, document: Path) -> Skill:
    if not _NAME.fullmatch(root.name):
        raise ValueError("skill directory name must be one identifier segment")
    if document.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("SKILL.md exceeds the 128000 byte limit")
    text = document.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML front matter")
    _, front, body = text.split("---\n", 2) if text.count("---\n") >= 2 else ("", "", "")
    metadata = _parse_front_matter(front)
    if not _NAME.fullmatch(metadata.name):
        raise ValueError("skill name must be one identifier segment")
    return Skill(
        skill_id=f"{origin}/{metadata.name}",
        name=metadata.name,
        description=metadata.description,
        root=root,
        origin=origin,
        body=body.lstrip("\n"),
    )


def _parse_front_matter(text: str) -> _FrontMatter:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator or key.strip() not in {"name", "description"}:
            raise ValueError("front matter supports only name and description")
        values[key.strip()] = value.strip().strip("\"'")
    return _FrontMatter.model_validate(values)


__all__ = ["SkillRegistry"]
