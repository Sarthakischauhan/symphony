"""Local plugin loading for coding_agent."""
from coding_agent.plugins.models import LoadedPlugin, PluginConfig, PluginContext, PluginDiagnostic
from coding_agent.plugins.manager import PluginManager
__all__ = ["LoadedPlugin", "PluginConfig", "PluginContext", "PluginDiagnostic", "PluginManager"]
