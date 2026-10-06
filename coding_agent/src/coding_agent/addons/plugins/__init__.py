"""Local plugin loading for coding_agent."""

from coding_agent.addons.plugins.manager import PluginManager
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
]
