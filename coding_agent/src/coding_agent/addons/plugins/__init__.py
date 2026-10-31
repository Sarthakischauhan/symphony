"""Local plugin loading for coding_agent."""

from coding_agent.addons.plugins.manager import PluginManager, bundled_plugins_root
from coding_agent.addons.plugins.models import (
    LoadedPlugin,
    PluginConfig,
    PluginContext,
    PluginDiagnostic,
    PluginLoadResult,
)

__all__ = [
    "LoadedPlugin",
    "PluginConfig",
    "PluginContext",
    "PluginDiagnostic",
    "PluginLoadResult",
    "PluginManager",
    "bundled_plugins_root",
]
