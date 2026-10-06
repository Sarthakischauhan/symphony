"""Optional Langfuse telemetry for coding-agent runs."""

from __future__ import annotations

from typing import Any

from coding_agent._lazy import resolve
from coding_agent.addons.langfuse.install import ensure_langfuse_installed, langfuse_available

_ADDON_EXPORTS = {
    "LangfuseAddon": ("coding_agent.addons.langfuse.addon", "LangfuseAddon"),
    "langfuse_from_config": ("coding_agent.addons.langfuse.addon", "langfuse_from_config"),
}

__all__ = [
    "LangfuseAddon",
    "ensure_langfuse_installed",
    "langfuse_available",
    "langfuse_from_config",
]


def __getattr__(name: str) -> Any:
    return resolve(globals(), name, _ADDON_EXPORTS)
