"""Install, update, remove, enable, disable and trust plugins.

Installing copies files into the cache and records them in ``state.json``. It
never imports, builds or runs anything from the plugin. A plugin with an addon
installs untrusted; only ``trust`` lets its code load.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from coding_agent.addons.plugins.manifest import read_manifest
from coding_agent.addons.plugins.marketplace import PluginOrigin, plugin_origin, read_marketplace
from coding_agent.addons.plugins.marketplaces import marketplace_root
from coding_agent.addons.plugins.resolve import ResolvedPlugin, resolve_plugins
from coding_agent.addons.plugins.state import PluginRecord, PluginState, load_state, plugins_dir, save_state
from coding_agent.addons.plugins.trust import addon_digest
from coding_agent.extensions.source import parse_source, stage

DIRECT = "direct"
_UNSAFE = re.compile(r"[^\w.+-]")


@dataclass(frozen=True)
class UpdateResult:
    key: str
    before: str
    after: str
    error: str = ""


def _origin(state: PluginState, record_marketplace: str, name: str) -> PluginOrigin:
    if record_marketplace not in state.marketplaces:
        raise ValueError(f"marketplace {record_marketplace!r} is not added; run: symphony plugins marketplace add <source>")
    root = marketplace_root(record_marketplace)
    return plugin_origin(read_marketplace(root).entry(name), root)


def _delete_cached(relative: str) -> None:
    """Delete a cached version, then the plugin and marketplace folders if that left them empty."""
    path = plugins_dir() / relative
    shutil.rmtree(path, ignore_errors=True)
    for parent in (path.parent, path.parent.parent):
        if parent.is_dir() and not any(parent.iterdir()) and parent != plugins_dir() / "cache":
            parent.rmdir()


def _install(state: PluginState, origin: PluginOrigin, *, marketplace: str, via: str) -> PluginRecord:
    """Stage, validate, then move into the cache. Nothing is written if validation fails."""
    plugins_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=plugins_dir(), prefix=".staging-") as scratch:
        staged = Path(scratch) / "plugin"
        revision = stage(origin.source, staged, sha=origin.sha)
        loaded = read_manifest(staged)
        name = loaded.manifest.name
        version = _UNSAFE.sub("_", loaded.manifest.version or revision[:12] or addon_digest(staged)[:12])
        destination = plugins_dir() / "cache" / marketplace / name / version
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), destination)
    key = f"{name}@{marketplace}"
    previous = state.plugins.get(key)
    record = PluginRecord(
        name=name, marketplace=marketplace, version=version, revision=revision, source=origin.source, via=via,
        path=destination.relative_to(plugins_dir()).as_posix(), installed=True,
        enabled=previous.enabled if previous else True,
        trusted_digest=previous.trusted_digest if previous else "",
    )
    if previous is not None and previous.path != record.path:
        _delete_cached(previous.path)
    state.plugins[key] = record
    return record


def install_plugin(text: str, *, cwd: Path, subdir: str = "") -> PluginRecord:
    """Install ``text``: a path, git URL[@ref], owner/repo, or plugin@marketplace."""
    source = parse_source(text, cwd=cwd, subdir=subdir)
    state = load_state()
    if source.kind == "marketplace":
        origin = _origin(state, source.marketplace, source.location)
        record = _install(state, origin, marketplace=source.marketplace, via=text)
    else:
        record = _install(state, PluginOrigin(source), marketplace=DIRECT, via="")
    save_state(state)
    return record


def update_plugins(name: str | None = None) -> list[UpdateResult]:
    """Re-fetch installed plugins from where they came from; trust lapses if the addon changed."""
    state = load_state()
    installed = {key: record for key, record in sorted(state.plugins.items()) if record.installed}
    if name is not None:
        installed = {key: record for key, record in installed.items() if name in {key, record.name}}
        if not installed:
            raise ValueError(f"no installed plugin named {name!r}; see: symphony plugins list")
    results: list[UpdateResult] = []
    for key, record in installed.items():
        before = record.version or record.revision[:12]
        try:
            origin = _origin(state, record.marketplace, record.name) if record.via else PluginOrigin(record.source)
            updated = _install(state, origin, marketplace=record.marketplace, via=record.via)
            results.append(UpdateResult(key, before, updated.version))
        except ValueError as exc:
            results.append(UpdateResult(key, before, before, str(exc)))
    save_state(state)
    return results


def remove_plugin(reference: str, workspace: Path) -> ResolvedPlugin:
    plugin = resolve_plugins(workspace).find(reference)
    state = load_state()
    record = state.plugins.get(plugin.key)
    if record is None or not record.installed:
        raise ValueError(f"{plugin.name} is not installed by symphony; it lives in {plugin.root}. Delete that directory to remove it.")
    _delete_cached(record.path)
    del state.plugins[plugin.key]
    save_state(state)
    return plugin


def _record(state: PluginState, plugin: ResolvedPlugin) -> PluginRecord:
    """The state entry for ``plugin``; a plugin found in place gets one the first time it is changed."""
    return state.plugins.get(plugin.key) or PluginRecord(name=plugin.name, path=str(plugin.root))


def set_enabled(reference: str, enabled: bool, workspace: Path) -> ResolvedPlugin:
    plugin = resolve_plugins(workspace).find(reference)
    state = load_state()
    state.plugins[plugin.key] = _record(state, plugin).model_copy(update={"enabled": enabled})
    save_state(state)
    return plugin


def set_trust(reference: str, trusted: bool, workspace: Path) -> ResolvedPlugin:
    """The only writer of trust. Records a digest of the addon directory, or clears it."""
    plugin = resolve_plugins(workspace).find(reference)
    if plugin.addon_root is None:
        raise ValueError(f"{plugin.name} has no addon, so there is nothing to trust. Its skills need no trust.")
    state = load_state()
    digest = addon_digest(plugin.addon_root) if trusted else ""
    state.plugins[plugin.key] = _record(state, plugin).model_copy(update={"trusted_digest": digest})
    save_state(state)
    return plugin


__all__ = [
    "DIRECT", "UpdateResult", "install_plugin", "remove_plugin", "set_enabled", "set_trust", "update_plugins",
]
