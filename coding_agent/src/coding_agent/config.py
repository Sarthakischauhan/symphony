"""Product configuration loaded from a spawn-time settings file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from core_harness.config import HarnessConfig
from coding_agent.plugins.models import PluginConfig

SPAWN_SETTINGS_NAME = "config.json"
SettingsSource = Union["CodingAgentConfig", str, Path]


class ApprovalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["ask", "always_allow"] = "ask"
    allow_answers: set[str] = Field(
        default_factory=lambda: {"y", "yes", "allow", "allow once", "a"}
    )
    broad_patch_chars: int = Field(default=400, ge=1)
    require_for_bash: bool = True
    require_for_overwrite: bool = True
    require_for_broad_patch: bool = True


class BashConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_timeout_seconds: int = Field(default=30, ge=1)
    max_timeout_seconds: int = Field(default=120, ge=1)
    max_output_bytes: int = Field(default=32000, ge=1)


class ReadFileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_text_bytes: int = Field(default=32000, ge=1)
    max_image_bytes: int = Field(default=8000000, ge=1)


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_max_results: int = Field(default=100, ge=1)
    default_max_line_chars: int = Field(default=240, ge=1)
    binary_sniff_bytes: int = Field(default=8192, ge=1)


class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bash: BashConfig = Field(default_factory=BashConfig)
    read_file: ReadFileConfig = Field(default_factory=ReadFileConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_output_tokens: int = Field(default=900, ge=1)
    max_lessons: int = Field(default=200, ge=1)
    context_limit: int = Field(default=6, ge=1)
    context_max_chars: int = Field(default=1400, ge=1)


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_skills: int = Field(default=100, ge=1)
    roots: list[Path] = Field(default_factory=list)


class PluginsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    entries: list[PluginConfig] = Field(default_factory=list)
    authorized_roots: list[Path] = Field(default_factory=list)


class CompactionConfig(BaseModel):
    """Bounds for the model-written compaction summary. Keep/drop limits live on ``harness``."""

    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(default=700, ge=1)
    max_transcript_chars: int = Field(default=24_000, ge=1)


def default_coding_agent_harness() -> HarnessConfig:
    """Product harness settings. Engine field defaults fill the rest."""
    return HarnessConfig(
        max_turns=24,
        max_tool_calls=40,
        max_runtime_seconds=600.0,
        tool_result_prune_tokens=48_000,
        context_warn_threshold=32_000,
        context_compact_threshold=16_000,
        context_target_tokens=80_000,
        compaction_keep_recent=10,
    )


class CodingAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness: HarnessConfig = Field(default_factory=default_coding_agent_harness)
    approvals: ApprovalConfig = Field(default_factory=ApprovalConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read config file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Config file {path} must contain a JSON object")
    return payload


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_tools(config: CodingAgentConfig) -> None:
    if config.tools.bash.default_timeout_seconds > config.tools.bash.max_timeout_seconds:
        raise ValueError(
            "tools.bash.default_timeout_seconds cannot exceed max_timeout_seconds"
        )


def symphony_dir() -> Path:
    """Return the user-wide Symphony data/config directory."""
    return (Path.home() / ".symphony").expanduser().resolve()


def spawn_settings_path(workspace: str | Path | None = None) -> Path:
    """Return the user-wide config file path.

    Configuration is shared across projects, just like sessions.  ``workspace``
    is retained as an ignored compatibility argument for callers that used the
    old project-local API.
    """
    del workspace
    return symphony_dir() / SPAWN_SETTINGS_NAME


def load_coding_agent_config(
    workspace: str | Path | None = None,
    *,
    path: str | Path | None = None,
) -> CodingAgentConfig:
    """Load a spawn settings file. Omitted keys use ``CodingAgentConfig`` field defaults."""
    if path is not None:
        source = Path(path).expanduser().resolve()
    elif workspace is not None:
        source = spawn_settings_path(workspace)
    else:
        raise ValueError("path or workspace is required")
    if not source.exists():
        raise ValueError(f"Config file does not exist: {source}")
    payload = _merge(CodingAgentConfig().model_dump(mode="json"), _read_json(source))
    config = CodingAgentConfig.model_validate(payload)
    _validate_tools(config)
    return config


def resolve_coding_agent_config(source: SettingsSource) -> CodingAgentConfig:
    if isinstance(source, CodingAgentConfig):
        return source
    return load_coding_agent_config(path=source)


def ensure_spawn_settings(
    workspace: str | Path,
    *,
    config: CodingAgentConfig | None = None,
    overrides: dict[str, Any] | None = None,
) -> CodingAgentConfig:
    """Create or refresh ``.symphony/config.json`` for this spawn and return it.

    An existing file is the starting point. Missing keys are filled from
    ``CodingAgentConfig`` field defaults, then the complete resolved settings
    are written back so the spawn file is the source of truth.
    """
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    path = spawn_settings_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)

    if config is not None:
        payload = config.model_dump(mode="json")
    elif path.exists():
        payload = _merge(CodingAgentConfig().model_dump(mode="json"), _read_json(path))
    else:
        payload = CodingAgentConfig().model_dump(mode="json")

    if overrides:
        payload = _merge(payload, overrides)

    resolved = CodingAgentConfig.model_validate(payload)
    _validate_tools(resolved)
    path.write_text(
        json.dumps(resolved.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return resolved


__all__ = [
    "ApprovalConfig",
    "BashConfig",
    "CodingAgentConfig",
    "CompactionConfig",
    "LearningConfig",
    "PluginsConfig",
    "ReadFileConfig",
    "SPAWN_SETTINGS_NAME",
    "SearchConfig",
    "SettingsSource",
    "SkillsConfig",
    "ToolsConfig",
    "ensure_spawn_settings",
    "load_coding_agent_config",
    "resolve_coding_agent_config",
    "spawn_settings_path",
]
