"""Local plugin loading for coding_agent."""
from coding_agent.plugins.models import PluginConfig, PluginContext, PluginDiagnostic
from coding_agent.plugins.manager import PluginManager
__all__ = ["PluginConfig", "PluginContext", "PluginDiagnostic", "PluginManager"]
