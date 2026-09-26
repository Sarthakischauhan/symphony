"""Safe discovery and bounded access to local Markdown skills."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from coding_agent.skills.frontmatter import SKILL_NAME, read_front_matter
from coding_agent.skills.models import Skill, SkillDiagnostic

if TYPE_CHECKING:
    from coding_agent.config import SkillsConfig

logger = logging.getLogger(__name__)
_MAX_FILE_BYTES = 128_000


def bundled_skills_root() -> Path:
    """Skills shipped in the package, so every install starts with the same habits without copying files."""
    return Path(__file__).resolve().parent.parent / "bundled_skills"


def default_skill_roots(config: SkillsConfig) -> list[tuple[str, Path]]:
    """Bundled skills, then ~/.symphony/skills, then configured roots; never the workspace.

    Why: a cloned repository must not be able to inject prompt text through its own skills folder.
    """
    return [
        ("bundled", bundled_skills_root()),
        ("user", Path.home() / ".symphony" / "skills"),
        *[("configured", root) for root in config.roots],
    ]


class SkillRegistry:
    """Discover skills and expose only paths within their skill roots."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills = {skill.skill_id: skill for skill in skills}

    @property
    def skills(self) -> tuple[Skill, ...]:
        return tuple(sorted(self._skills.values(), key=lambda skill: skill.skill_id))

    def catalog_prompt(self) -> str:
        """The system-prompt skill catalog, or "" when no skills are loaded."""
        if not self.skills:
            return ""
        lines = ["Available skills (read the listed SKILL.md with read_file when relevant):"]
        lines.extend(skill.catalog_line() for skill in self.skills)
        return "\n".join(lines)

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
        """Load every SKILL.md under ``roots``; a broken skill becomes a diagnostic, never a crash."""
        found: list[Skill] = []
        diagnostics: list[SkillDiagnostic] = []
        seen: set[str] = set()
        for origin, root in roots:
            root = root.expanduser().resolve()
            if not root.is_dir():
                continue
            candidates = (
                [root] if (root / "SKILL.md").is_file() else sorted(path for path in root.iterdir() if path.is_dir())
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
                except (OSError, UnicodeError, ValueError) as exc:
                    logger.warning("Skipping skill %s: %s", document, exc)
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
    if not SKILL_NAME.fullmatch(root.name):
        raise ValueError("skill directory name must be one identifier segment")
    if document.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("SKILL.md exceeds the 128000 byte limit")
    text = document.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n")
    meta = read_front_matter(text)
    return Skill(
        skill_id=f"{origin}/{meta.name}",
        name=meta.name,
        description=meta.description,
        root=root,
        origin=origin,
        args=meta.args,
    )


__all__ = ["SkillRegistry", "bundled_skills_root", "default_skill_roots"]
