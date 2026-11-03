"""Add, update and remove skills, and change how the catalog lists them.

``add`` copies a skill (or every skill in a collection) from a local path or git
repository into ``<symphony home>/skills/<name>``, or into the project's
``.agents/skills`` with ``project=True``. Nothing in a skill is run. Each
installed skill keeps a ``.symphony-source.json`` so ``update`` can fetch it
again and ``remove`` knows it is safe to delete.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from coding_agent.addons.skills.models import SkillSource
from coding_agent.addons.skills.registry import parse_skill, skill_directories
from coding_agent.config import CodingAgentConfig, SkillSetting, ensure_spawn_settings, symphony_dir
from coding_agent.extensions import project_root
from coding_agent.extensions.source import Source, parse_source, stage

PROVENANCE = ".symphony-source.json"


class SkillProvenance(BaseModel):
    """Where an installed skill came from: the exact directory to fetch again."""

    model_config = ConfigDict(extra="forbid")

    source: Source
    revision: str = ""


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    path: Path
    scope: str


@dataclass(frozen=True)
class SkillUpdate:
    name: str
    before: str
    after: str
    error: str = ""


def skills_directory(workspace: Path, *, project: bool) -> Path:
    return project_root(workspace) / ".agents" / "skills" if project else symphony_dir() / "skills"


def _managed(workspace: Path) -> list[tuple[str, Path]]:
    """Skills ``skills add`` installed: ``(scope, directory)`` for user then project."""
    found: list[tuple[str, Path]] = []
    for scope, project in (("user", False), ("project", True)):
        base = skills_directory(workspace, project=project)
        if base.is_dir():
            found += [(scope, path) for path in sorted(base.iterdir()) if (path / PROVENANCE).is_file()]
    return found


def _read_provenance(directory: Path) -> SkillProvenance:
    return SkillProvenance.model_validate(json.loads((directory / PROVENANCE).read_text(encoding="utf-8")))


def _relative(staged: Path, directory: Path) -> str:
    return "" if directory == staged else directory.relative_to(staged).as_posix()


def add_skills(text: str, *, workspace: Path, cwd: Path, project: bool = False, subdir: str = "") -> list[InstalledSkill]:
    """Install every skill found at ``text`` (a path, git URL[@ref] or owner/repo)."""
    source = parse_source(text, cwd=cwd, subdir=subdir, marketplaces=False)
    base = skills_directory(workspace, project=project)
    with tempfile.TemporaryDirectory(prefix="symphony-skills-") as scratch:
        staged = Path(scratch) / "source"
        revision = stage(source, staged)
        directories = skill_directories(staged)
        if not directories:
            raise ValueError(f"no SKILL.md found in {source.describe()}")
        plan: list[tuple[str, Path]] = []
        for directory in directories:
            name = parse_skill(SkillSource("install", staged), directory, directory / "SKILL.md").name
            target = base / name
            if target.exists():
                raise ValueError(f"{target} already exists; update it with 'symphony skills update {name}' or remove it first")
            plan.append((name, directory))
        if len({name for name, _ in plan}) != len(plan):
            raise ValueError("the source contains two skills with the same name")
        base.mkdir(parents=True, exist_ok=True)
        installed: list[InstalledSkill] = []
        for name, directory in plan:
            target = base / name
            shutil.copytree(directory, target, ignore=shutil.ignore_patterns(".git"))
            relative = _relative(staged, directory)
            where = "/".join(part for part in (source.subdir, relative) if part)
            provenance = SkillProvenance(
                source=Source(source.kind, source.location, source.ref, where), revision=revision,
            )
            (target / PROVENANCE).write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
            installed.append(InstalledSkill(name, target, "project" if project else "user"))
    return installed


def update_skills(name: str | None, *, workspace: Path) -> list[SkillUpdate]:
    """Fetch installed skills again from where they came from."""
    managed = [(scope, path) for scope, path in _managed(workspace) if name in {None, path.name}]
    if name is not None and not managed:
        raise ValueError(f"no skill named {name!r} was installed by 'symphony skills add'")
    results: list[SkillUpdate] = []
    for _, directory in managed:
        provenance = _read_provenance(directory)
        try:
            with tempfile.TemporaryDirectory(prefix="symphony-skills-") as scratch:
                staged = Path(scratch) / "source"
                revision = stage(provenance.source, staged)
                parse_skill(SkillSource("update", staged), staged, staged / "SKILL.md")
                shutil.rmtree(directory)
                shutil.copytree(staged, directory)
                updated = SkillProvenance(source=provenance.source, revision=revision)
                (directory / PROVENANCE).write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
            results.append(SkillUpdate(directory.name, provenance.revision[:12], revision[:12]))
        except (OSError, ValueError) as exc:
            results.append(SkillUpdate(directory.name, provenance.revision[:12], provenance.revision[:12], str(exc)))
    return results


def remove_skill(name: str, *, workspace: Path) -> Path:
    """Delete a skill that ``skills add`` installed. Hand-made skills are never deleted."""
    for _, directory in _managed(workspace):
        if directory.name == name:
            shutil.rmtree(directory)
            return directory
    raise ValueError(f"{name!r} was not installed by 'symphony skills add'; delete its directory yourself if you want it gone")


def _write(workspace: Path, change: dict[str, object]) -> CodingAgentConfig:
    config = ensure_spawn_settings(workspace)
    config = config.model_copy(update={"skills": config.skills.model_copy(update=change)})
    return ensure_spawn_settings(workspace, config=config)


def set_skill_enabled(name: str, enabled: bool, *, workspace: Path) -> None:
    """Disabled skills are not loaded. Saved in ``skills.disabled`` of the Symphony config."""
    disabled = set(ensure_spawn_settings(workspace).skills.disabled)
    disabled = disabled | {name} if not enabled else disabled - {name}
    _write(workspace, {"disabled": sorted(disabled)})


def set_skill_mode(name: str, mode: SkillSetting | None, *, workspace: Path) -> None:
    """Set how the catalog lists one skill (``None`` goes back to its own default)."""
    settings = dict(ensure_spawn_settings(workspace).skills.settings)
    if mode is None:
        settings.pop(name, None)
    else:
        settings[name] = mode
    _write(workspace, {"settings": settings})


__all__ = [
    "PROVENANCE", "InstalledSkill", "SkillProvenance", "SkillUpdate", "add_skills", "remove_skill",
    "set_skill_enabled", "set_skill_mode", "skills_directory", "update_skills",
]
