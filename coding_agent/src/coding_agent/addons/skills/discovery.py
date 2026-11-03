"""Resolve every skill source for a workspace into one registry and one catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from coding_agent.addons.skills.catalog import SkillCatalog, build_catalog
from coding_agent.addons.skills.models import SkillSource
from coding_agent.addons.skills.registry import SkillRegistry
from coding_agent.config import SkillsConfig
from coding_agent.extensions import Diagnostic, extension_roots


@dataclass(frozen=True)
class SkillSet:
    """What one agent knows about skills: all of them, what the prompt lists, and what went wrong."""

    registry: SkillRegistry
    catalog: SkillCatalog
    diagnostics: tuple[Diagnostic, ...]


def skill_sources(
    workspace: str | Path,
    config: SkillsConfig,
    plugin_sources: Iterable[SkillSource] = (),
) -> list[SkillSource]:
    """Precedence order: project, user, ~/.agents, configured roots, plugins, bundled."""
    roots = extension_roots(workspace)
    sources = [SkillSource(root.scope, root.skills) for root in roots if root.scope != "bundled"]
    sources += [SkillSource("configured", root) for root in config.roots]
    sources += list(plugin_sources)
    sources += [SkillSource(root.scope, root.skills) for root in roots if root.scope == "bundled"]
    return sources


def discover_skills(
    workspace: str | Path,
    config: SkillsConfig,
    plugin_sources: Iterable[SkillSource] = (),
) -> SkillSet:
    registry, diagnostics = SkillRegistry.discover(
        skill_sources(workspace, config, plugin_sources), max_skills=config.max_skills,
    )
    catalog = build_catalog(
        registry.skills,
        settings=config.settings,
        disabled=frozenset(config.disabled),
        max_tokens=config.max_context_tokens,
    )
    return SkillSet(registry, catalog, diagnostics + catalog.notices)


__all__ = ["SkillSet", "discover_skills", "skill_sources"]
