"""Plugins: find them, validate them, install them, decide whether their code may load.

This package executes nothing. It hands a plugin's skill directories to
``addons/skills`` and the addon directories of enabled plugins to the addon loader.
"""

from coding_agent.addons.plugins.install import (
    UpdateResult,
    install_plugin,
    remove_plugin,
    set_enabled,
    update_plugins,
)
from coding_agent.addons.plugins.manifest import LoadedManifest, PluginManifest, read_manifest
from coding_agent.addons.plugins.marketplaces import (
    add_marketplace,
    list_marketplaces,
    remove_marketplace,
    update_marketplaces,
)
from coding_agent.addons.plugins.resolve import PluginSet, ResolvedPlugin, resolve_plugins

__all__ = [
    "LoadedManifest",
    "PluginManifest",
    "PluginSet",
    "ResolvedPlugin",
    "UpdateResult",
    "add_marketplace",
    "install_plugin",
    "list_marketplaces",
    "read_manifest",
    "remove_marketplace",
    "remove_plugin",
    "resolve_plugins",
    "set_enabled",
    "update_marketplaces",
    "update_plugins",
]
