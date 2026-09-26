"""Load the plugins a CodingAgent mounts: configured entries plus discovered installs.

Why: the trust decision (which roots may run addon code) must come from the
process environment, never from config, and any plugin failure stops startup
instead of running with a partial plugin set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from coding_agent.plugins.manager import PluginManager
from coding_agent.plugins.models import PluginLoadResult

if TYPE_CHECKING:
    from coding_agent.config import PluginsConfig


def load_authorized_plugins(workspace: Path, config: PluginsConfig) -> PluginLoadResult:
    """Load configured and discovered plugins; raise ``ValueError`` on any diagnostic."""
    # Global config must not be able to authorize executable code.
    # Authorization is supplied by the trusted process environment;
    # config may only select already-authorized plugins.
    trusted_roots = [
        Path(value) for value in os.environ.get("SYMPHONY_PLUGIN_AUTHORIZED_ROOTS", "").split(os.pathsep) if value
    ]
    plugin_manager = PluginManager(workspace, authorized_roots=trusted_roots)
    configured_plugins = tuple(config.entries)
    discovered_plugins = plugin_manager.discover()
    # Explicit entries override auto-discovered paths by resolved path;
    # this keeps the installed layout convenient without losing settings.
    configured_paths = {entry.path.expanduser().resolve() for entry in configured_plugins}
    plugin_entries = configured_plugins + tuple(
        entry for entry in discovered_plugins if entry.path.expanduser().resolve() not in configured_paths
    )
    result = plugin_manager.load(plugin_entries)
    if result.diagnostics:
        details = "; ".join(f"{diagnostic.source}: {diagnostic.message}" for diagnostic in result.diagnostics)
        raise ValueError(f"Plugin loading failed: {details}")
    return result


__all__ = ["load_authorized_plugins"]
