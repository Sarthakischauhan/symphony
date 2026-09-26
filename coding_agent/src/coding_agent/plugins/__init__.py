"""Local plugin loading for coding_agent."""

from coding_agent.plugins.models import LoadedPlugin, PluginConfig, PluginContext, PluginDiagnostic, PluginLoadResult
from coding_agent.plugins.manager import PluginManager
from coding_agent.plugins.authorized_plugins import load_authorized_plugins

__all__ = [
    "LoadedPlugin",
    "PluginConfig",
    "PluginContext",
    "PluginDiagnostic",
    "PluginLoadResult",
    "PluginManager",
    "load_authorized_plugins",
]
