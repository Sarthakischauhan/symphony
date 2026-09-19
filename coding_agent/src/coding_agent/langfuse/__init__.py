"""Optional Langfuse telemetry for coding-agent runs."""

from coding_agent.langfuse.addon import LangfuseAddon, langfuse_from_config
from coding_agent.langfuse.install import ensure_langfuse_installed, langfuse_available

__all__ = [
    "LangfuseAddon",
    "ensure_langfuse_installed",
    "langfuse_available",
    "langfuse_from_config",
]
