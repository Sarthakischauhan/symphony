"""Safe discovery of local Markdown skills.

Discovery reads front matter only. It never imports or runs anything in a skill.
The model reads a skill's body itself, with the ordinary read tool, from the
path the catalog gives it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from coding_agent.addons.skills.frontmatter import SKILL_NAME, read_front_matter
from coding_agent.addons.skills.models import Skill, SkillSource
from coding_agent.extensions import Diagnostic

logger = logging.getLogger(__name__)
MAX_SKILL_FILE_BYTES = 128_000
MAX_SKILL_WALK_DEPTH = 4


class SkillRegistry:
    """The skills found across all sources; the earliest source keeps a contested name."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills = {skill.name: skill for skill in skills}

    @property
    def skills(self) -> tuple[Skill, ...]:
        """Sorted by name, so every consumer sees one stable order."""
        return tuple(sorted(self._skills.values(), key=lambda skill: skill.name))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    @classmethod
    def discover(
        cls,
        sources: Iterable[SkillSource],
        *,
        max_skills: int = 100,
    ) -> tuple["SkillRegistry", tuple[Diagnostic, ...]]:
        """Load every SKILL.md under ``sources``; a broken skill becomes a diagnostic, never a crash."""
        found: dict[str, Skill] = {}
        diagnostics: list[Diagnostic] = []
        for source in sources:
            root = source.path.expanduser().resolve()
            if not root.is_dir():
                continue
            for skill_root in skill_directories(root):
                document = skill_root / "SKILL.md"
                try:
                    skill = parse_skill(source, skill_root, document)
                except (OSError, UnicodeError, ValueError) as exc:
                    logger.warning("Skipping skill %s: %s", document, exc)
                    diagnostics.append(Diagnostic(str(document), str(exc)))
                    continue
                winner = found.get(skill.name)
                if winner is not None:
                    diagnostics.append(Diagnostic(
                        str(document),
                        f"skill {skill.name!r} is shadowed by the {winner.origin} skill at {winner.path}",
                        "notice",
                    ))
                elif len(found) >= max_skills:
                    diagnostics.append(Diagnostic(str(document), "skill limit reached"))
                else:
                    found[skill.name] = skill
        return cls(found.values()), tuple(diagnostics)


def skill_directories(root: Path, *, max_depth: int = MAX_SKILL_WALK_DEPTH) -> list[Path]:
    """Directories under ``root`` that contain ``SKILL.md``.

    A root that is itself a skill is returned alone. Otherwise walk downward,
    bounded by ``max_depth``, so ``~/.symphony/skills/<name>`` and a nested
    collection such as ``skills/team/<name>`` both load. Symlinks are skipped.
    """
    if (root / "SKILL.md").is_file():
        return [root]
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        children = sorted(
            path for path in directory.iterdir() if path.is_dir() and not path.is_symlink()
        )
        for child in children:
            if (child / "SKILL.md").is_file():
                found.append(child)
                continue
            walk(child, depth + 1)

    walk(root, 1)
    return found


def parse_skill(source: SkillSource, root: Path, document: Path) -> Skill:
    if not SKILL_NAME.fullmatch(root.name):
        raise ValueError("skill directory name must be one identifier segment")
    if document.stat().st_size > MAX_SKILL_FILE_BYTES:
        raise ValueError("SKILL.md exceeds the 128000 byte limit")
    text = document.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n")
    meta = read_front_matter(text)
    name = f"{source.namespace}:{meta.name}" if source.namespace else meta.name
    return Skill(name=name, description=meta.description, path=document, origin=source.origin,
                 invocation=meta.invocation, args=meta.args)


__all__ = ["MAX_SKILL_FILE_BYTES", "SkillRegistry", "parse_skill", "skill_directories"]
