"""Local plugin loading for coding_agent."""

from coding_agent.plugins.manager import PluginManager
from coding_agent.plugins.models import (
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
