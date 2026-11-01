"""Find every plugin a workspace can use, and decide what each may do.

This only reads: manifests, directories, the state file. No plugin code runs.
It answers two questions per plugin: is it enabled, and which skill directories
does it add. An enabled plugin's addon is loaded; disabling it is how you stop that.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from coding_agent.addons.plugins.manifest import LoadedManifest, read_manifest
from coding_agent.addons.plugins.state import PluginState, load_state, plugins_dir
from coding_agent.addons.skills.models import SkillSource
from coding_agent.addons.skills.registry import skill_directories
from coding_agent.extensions import Diagnostic, extension_roots

Scope = Literal["project", "user", "agents", "installed"]
_RESERVED_DIRECTORIES = frozenset({"cache", "marketplaces"})
_DEFAULT_SKILLS = "./skills/"


@dataclass(frozen=True)
class ResolvedPlugin:
    """One plugin as the agent will treat it."""

    key: str
    name: str
    version: str
    description: str
    root: Path
    scope: Scope
    enabled: bool
    skill_dirs: tuple[Path, ...]
    skill_count: int
    addon_root: Path | None
    skipped: tuple[tuple[str, str], ...]

    @property
    def runs_addon(self) -> bool:
        return self.enabled and self.addon_root is not None

    @property
    def addon_note(self) -> str:
        if self.addon_root is None:
            return ""
        if self.enabled:
            return "addon loads while this plugin is enabled"
        return f"addon not loaded: plugin disabled (run: symphony plugins enable {self.name})"

    @property
    def skill_sources(self) -> tuple[SkillSource, ...]:
        return tuple(SkillSource(f"plugin:{self.name}", path, self.name) for path in self.skill_dirs)


@dataclass(frozen=True)
class PluginSet:
    """Every plugin found, plus what went wrong finding them."""

    plugins: tuple[ResolvedPlugin, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def skill_sources(self) -> tuple[SkillSource, ...]:
        """Skill directories of enabled plugins, handed to ``addons/skills``."""
        return tuple(source for plugin in self.plugins if plugin.enabled for source in plugin.skill_sources)

    @property
    def addon_roots(self) -> tuple[Path, ...]:
        """Addon directories of enabled plugins, handed to the addon loader."""
        return tuple(plugin.addon_root for plugin in self.plugins if plugin.runs_addon and plugin.addon_root)

    def find(self, reference: str) -> ResolvedPlugin:
        """Look up by ``name``, ``name@marketplace`` or key; an ambiguous bare name is an error."""
        matches = [item for item in self.plugins if reference in {item.key, item.name}]
        if not matches:
            raise ValueError(f"no plugin named {reference!r}; see: symphony plugins list")
        if len(matches) > 1:
            raise ValueError(f"{reference!r} is ambiguous: use one of {', '.join(item.key for item in matches)}")
        return matches[0]


def _candidates(workspace: Path, state: PluginState) -> Iterable[tuple[Scope, Path, str]]:
    roots = [root for root in extension_roots(workspace) if root.plugins is not None]
    for root in roots:
        if root.scope == "project":
            yield from _in_place(root.scope, root.plugins)
    for key, record in sorted(state.plugins.items()):
        if record.installed:
            yield "installed", plugins_dir() / record.path, key
    for root in roots:
        if root.scope != "project":
            yield from _in_place(root.scope, root.plugins)


def _in_place(scope: Scope, directory: Path | None) -> Iterable[tuple[Scope, Path, str]]:
    if directory is None or not directory.is_dir():
        return
    for child in sorted(directory.iterdir()):
        if child.is_dir() and not child.is_symlink() and child.name not in _RESERVED_DIRECTORIES and not child.name.startswith("."):
            resolved = child.resolve()
            yield scope, resolved, f"path:{resolved}"


def _skill_dirs(loaded: LoadedManifest, diagnostics: list[Diagnostic]) -> tuple[Path, ...]:
    found: list[Path] = []
    root = loaded.root.resolve()
    for declared in loaded.manifest.skills:
        path = (root / declared).resolve()
        if path.is_dir() and path.is_relative_to(root):
            found.append(path)
        elif declared != _DEFAULT_SKILLS:
            diagnostics.append(Diagnostic(str(loaded.path), f"skills path {declared!r} is not a directory inside the plugin"))
    return tuple(found)


def resolve_plugins(workspace: str | Path, state: PluginState | None = None) -> PluginSet:
    """Resolve plugins for ``workspace``. A broken plugin is a diagnostic, never an exception."""
    workspace = Path(workspace).expanduser().resolve()
    diagnostics: list[Diagnostic] = []
    if state is None:
        try:
            state = load_state()
        except ValueError as exc:
            return PluginSet((), (Diagnostic(str(plugins_dir() / "state.json"), str(exc)),))
    plugins: dict[str, ResolvedPlugin] = {}
    for scope, root, key in _candidates(workspace, state):
        try:
            loaded = read_manifest(root)
            symphony = loaded.manifest.symphony
        except ValueError as exc:
            diagnostics.append(Diagnostic(str(root), str(exc)))
            continue
        name = loaded.manifest.name
        if name in plugins:
            diagnostics.append(Diagnostic(str(root), f"plugin {name!r} is shadowed by the one at {plugins[name].root}", "notice"))
            continue
        record = state.plugins.get(key)
        addon_root = (root / symphony.addons).resolve() if symphony else None
        if addon_root is not None and not addon_root.is_relative_to(root):
            diagnostics.append(Diagnostic(str(root), "extensions.symphony.addons leaves the plugin"))
            continue
        skill_dirs = _skill_dirs(loaded, diagnostics)
        plugins[name] = ResolvedPlugin(
            key=key, name=name, version=loaded.manifest.version, description=loaded.manifest.description,
            root=root, scope=scope, enabled=record.enabled if record else True,
            skill_dirs=skill_dirs, skill_count=sum(len(skill_directories(path)) for path in skill_dirs), addon_root=addon_root,
            skipped=loaded.skipped,
        )
    return PluginSet(tuple(plugins.values()), tuple(diagnostics))


__all__ = ["PluginSet", "ResolvedPlugin", "resolve_plugins"]
