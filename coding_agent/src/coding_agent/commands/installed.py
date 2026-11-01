"""The text report of what is installed: skills with their catalog cost, plugins, skipped parts, notices.

``/installed`` in stdio and ``symphony skills|plugins list`` use it; the TUI shows the
same data in ``ExtensionsModal``.
"""

from __future__ import annotations

from pathlib import Path

from coding_agent.addons.plugins import PluginSet, ResolvedPlugin, resolve_plugins
from coding_agent.addons.skills import CatalogEntry, SkillSet, discover_skills
from coding_agent.commands.cli_support import table
from coding_agent.config import CodingAgentConfig, load_coding_agent_config, spawn_settings_path
from coding_agent.extensions import Diagnostic

STATE_LABEL = {"full": "on", "name-only": "name only", "manual": "manual", "off": "off", "omitted": "over budget"}


def saved_config(workspace: Path) -> CodingAgentConfig:
    """The user's saved config, or the defaults when none is saved yet."""
    if spawn_settings_path(workspace).exists():
        return load_coding_agent_config(workspace)
    return CodingAgentConfig()


def discover(workspace: Path, config: CodingAgentConfig | None = None) -> tuple[SkillSet, PluginSet]:
    """What an agent started in ``workspace`` would load, without starting one."""
    config = config or saved_config(workspace)
    plugins = resolve_plugins(workspace) if config.plugins.enabled else PluginSet()
    return discover_skills(workspace, config.skills, plugins.skill_sources), plugins


def skills_report(skills: SkillSet, budget: int, *, paths: bool = True) -> str:
    entries = skills.registry.skills
    catalog = skills.catalog
    head = f"Skills ({len(entries)}) · catalog {catalog.tokens}/{budget} tokens"
    if not catalog.entries:
        return head
    rows = [_skill_row(entry, paths) for entry in catalog.entries]
    header = ("NAME", "MODE", "TOKENS", "ORIGIN") + (("PATH",) if paths else ())
    return head + "\n" + table(header, rows)


def _skill_row(entry: CatalogEntry, paths: bool) -> tuple[str, ...]:
    row = (entry.skill.name, STATE_LABEL[entry.state], str(entry.tokens or "-"), entry.skill.origin)
    return row + ((str(entry.skill.path),) if paths else ())


def plugin_state(plugin: ResolvedPlugin) -> str:
    return "enabled" if plugin.enabled else "disabled"


def plugin_details(plugin: ResolvedPlugin) -> list[str]:
    """Indented lines under a plugin row: addon trust and each skipped contribution with its reason."""
    lines = [f"    {plugin.addon_note}"] if plugin.addon_note else []
    lines += [f"    skipped {label}: {reason}" for label, reason in plugin.skipped]
    return lines


def plugins_report(plugins: PluginSet) -> str:
    if not plugins.plugins:
        return "Plugins (0)"
    rows = [
        (p.name, p.version or "-", plugin_state(p), p.scope, str(p.skill_count), str(p.root))
        for p in plugins.plugins
    ]
    lines = ["Plugins (%d)" % len(plugins.plugins), *table(("NAME", "VERSION", "STATE", "SCOPE", "SKILLS", "PATH"), rows).splitlines()]
    for plugin in plugins.plugins:
        details = plugin_details(plugin)
        if details:
            lines += [f"  {plugin.name}:", *details]
    return "\n".join(lines)


def diagnostics_report(diagnostics: tuple[Diagnostic, ...]) -> str:
    if not diagnostics:
        return ""
    return "Notices (%d)\n" % len(diagnostics) + "\n".join(f"  {item.level}: {item.render()}" for item in diagnostics)


def installed_report(skills: SkillSet, plugins: PluginSet, budget: int) -> str:
    parts = [skills_report(skills, budget), plugins_report(plugins), diagnostics_report(plugins.diagnostics + skills.diagnostics)]
    return "\n\n".join(part for part in parts if part)


__all__ = [
    "STATE_LABEL", "diagnostics_report", "discover", "installed_report", "plugin_details", "plugin_state",
    "plugins_report", "saved_config", "skills_report",
]
