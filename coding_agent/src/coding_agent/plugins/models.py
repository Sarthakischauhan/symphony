"""Validated local plugin configuration and runtime context."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from coding_agent.skills.models import SkillArg

class PluginConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)

@dataclass(frozen=True)
class PluginContext:
    workspace: Path
    root: Path
    config: dict[str, Any]

@dataclass(frozen=True)
class PluginDiagnostic:
    source: str
    message: str

@dataclass(frozen=True)
class LoadedPlugin:
    """A discovered plugin after its manifest is validated.

    ``args`` is the contract declared on the manifest. Discovery does not
    execute addon code to learn them.
    """

    plugin_id: str
    description: str
    root: Path
    enabled: bool
    args: tuple[SkillArg, ...] = ()

__all__ = ["PluginConfig", "PluginContext", "PluginDiagnostic", "LoadedPlugin"]
