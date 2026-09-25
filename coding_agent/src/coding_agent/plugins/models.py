"""Validated local plugin configuration and runtime context."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple
from pydantic import BaseModel, ConfigDict, Field

from coding_agent.extension_args import Description

class PluginConfig(BaseModel):
    """One plugin entry from config or discovery; strict so typos are reported."""
    model_config = ConfigDict(extra="forbid")
    path: Path
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)

class PluginMetadata(BaseModel):
    """The display fields of plugin.json; the loader validates the other keys itself."""
    model_config = ConfigDict(extra="ignore")
    description: Description = ""  # Optional: pydantic does not validate the default.

@dataclass(frozen=True)
class PluginContext:
    """What an authorized addon factory receives."""
    workspace: Path
    root: Path
    config: dict[str, Any]

@dataclass(frozen=True)
class PluginDiagnostic:
    """A manifest or addon failure, reported instead of raised."""
    source: str
    message: str

@dataclass(frozen=True)
class LoadedPlugin:
    """A plugin whose manifest validated, read without executing addon code."""
    plugin_id: str
    description: str
    root: Path
    enabled: bool

class PluginLoadResult(NamedTuple):
    """Everything PluginManager.load produced; ``plugins`` includes disabled manifests."""
    addons: list[Any]
    skill_roots: list[tuple[str, Path]]
    plugins: tuple[LoadedPlugin, ...]
    diagnostics: tuple[PluginDiagnostic, ...]

__all__ = ["LoadedPlugin", "PluginConfig", "PluginContext", "PluginDiagnostic", "PluginLoadResult", "PluginMetadata"]
