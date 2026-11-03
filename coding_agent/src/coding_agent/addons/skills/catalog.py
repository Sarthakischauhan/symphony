"""The skill catalog: one prompt block listing each skill's name, description and SKILL.md path.

The body of a skill is never in the prompt. The model reads the file at the
listed path with its ordinary read tool when a skill matches the task.

The block is a pure function of the skill set and its settings: skills are sorted
by name and the budget trims by a fixed rule, so the prompt prefix changes only
when the set (or a setting) does, and prompt caching survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from core_harness.context import estimate_text_tokens

from coding_agent.addons.skills.models import CATALOG_DESCRIPTION_CHARS, Skill, SkillMode
from coding_agent.extensions import Diagnostic

CATALOG_HEADER = "Skills (when a skill matches the task, read its SKILL.md at the path shown before acting on that task):"
EntryState = Literal["full", "name-only", "manual", "off", "omitted"]


@dataclass(frozen=True)
class CatalogEntry:
    """One skill's place in the catalog and what that costs in prompt tokens."""

    skill: Skill
    state: EntryState
    line: str = ""

    @property
    def tokens(self) -> int:
        return estimate_text_tokens(self.line + "\n") if self.line else 0


@dataclass(frozen=True)
class SkillCatalog:
    """Every skill with its state, the prompt block, and notices about trimming."""

    entries: tuple[CatalogEntry, ...] = ()
    text: str = ""
    tokens: int = 0
    notices: tuple[Diagnostic, ...] = ()


def _line(skill: Skill, state: EntryState) -> str:
    if state == "name-only":
        return f"- {skill.name} (file: {skill.path})"
    description = skill.description
    if len(description) > CATALOG_DESCRIPTION_CHARS:
        description = description[: CATALOG_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return f"- {skill.name}: {description} (file: {skill.path})"


def effective_mode(skill: Skill, settings: Mapping[str, SkillMode], disabled: frozenset[str]) -> SkillMode:
    """A disabled skill is off; else an explicit setting; else the skill's own invocation."""
    if skill.name in disabled:
        return "off"
    return settings.get(skill.name) or ("manual" if skill.invocation == "manual" else "on")


def build_catalog(
    skills: tuple[Skill, ...],
    *,
    settings: Mapping[str, SkillMode],
    disabled: frozenset[str] = frozenset(),
    max_tokens: int,
) -> SkillCatalog:
    """Fit the listed skills into ``max_tokens``.

    When they do not fit, the skills with the longest lines lose their descriptions
    first (ties by name); if names and paths alone still do not fit, the last names
    in alphabetical order are left out. Both are reported as notices.
    """
    states: dict[str, EntryState] = {}
    for skill in skills:
        mode = effective_mode(skill, settings, disabled)
        states[skill.name] = "full" if mode == "on" else mode
    ordered = sorted(skills, key=lambda skill: skill.name)
    listed = [skill for skill in ordered if states[skill.name] in {"full", "name-only"}]
    header = estimate_text_tokens(CATALOG_HEADER + "\n")

    def cost() -> int:
        return header + sum(estimate_text_tokens(_line(skill, states[skill.name]) + "\n") for skill in listed)

    notices: list[Diagnostic] = []
    trimmed = sorted(
        (skill for skill in listed if states[skill.name] == "full"),
        key=lambda skill: (-len(_line(skill, "full")), skill.name),
    )
    for skill in trimmed:
        if cost() <= max_tokens:
            break
        states[skill.name] = "name-only"
        notices.append(Diagnostic(skill.name, f"description left out to fit the {max_tokens} token skill catalog budget", "notice"))
    while listed and cost() > max_tokens:
        skill = listed.pop()
        states[skill.name] = "omitted"
        notices.append(Diagnostic(skill.name, f"left out of the skill catalog: over the {max_tokens} token budget", "notice"))
    entries = tuple(
        CatalogEntry(skill, states[skill.name], _line(skill, states[skill.name]) if states[skill.name] in {"full", "name-only"} else "")
        for skill in ordered
    )
    lines = [entry.line for entry in entries if entry.line]
    text = "\n".join([CATALOG_HEADER, *lines]) if lines else ""
    return SkillCatalog(entries, text, cost() if lines else 0, tuple(notices))


__all__ = ["CATALOG_HEADER", "CatalogEntry", "SkillCatalog", "build_catalog", "effective_mode"]
