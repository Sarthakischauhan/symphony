"""JSON-backed configuration owned by the harness engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SettingsSource = Union["HarnessConfig", str, Path]

DEFAULT_SUBAGENT_SYSTEM_PROMPT = (
    "You are a subagent spawned to complete one focused task. Use tools as "
    "needed. Do not ask the user. Return a concise, complete answer for the "
    "parent agent."
)


def default_context_limits() -> dict[str, int]:
    """Known model context windows used when a settings file omits them."""
    return {
        "gpt-5.6-luna": 400000,
        "gpt-5.4-mini": 400000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4.1": 1047576,
        "gpt-4.1-mini": 1047576,
        "gpt-4.1-nano": 1047576,
        "claude-fable-5": 200000,
        "claude-haiku-4-5": 200000,
        "claude-opus-5": 200000,
        "claude-sonnet-5": 200000,
        "gemini": 1048576,
        "gemini-3.1-pro-preview": 1048576,
        "gemini-3.5-flash": 1048576,
        "gemini-3.6-flash": 1048576,
        "gemini-3.7-flash": 1048576,
    }


class HarnessConfig(BaseModel):
    """Runtime limits and policies that belong to ``core_harness``."""

    model_config = ConfigDict(extra="forbid")

    max_turns: int = Field(default=8, ge=1)
    max_tool_calls: Optional[int] = Field(default=None, ge=1)
    max_runtime_seconds: Optional[float] = Field(default=None, gt=0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    tool_result_max_chars: Optional[int] = Field(default=4000, ge=1)
    tool_result_keep_recent: int = Field(default=8, ge=0)
    tool_result_prune_tokens: Optional[int] = Field(default=None, ge=0)
    context_warn_threshold: Optional[int] = Field(default=None, ge=0)
    context_compact_threshold: Optional[int] = Field(default=None, ge=0)
    context_target_tokens: Optional[int] = Field(default=None, ge=1)
    compaction_keep_recent: int = Field(default=10, ge=1)
    max_spawn_depth: int = Field(default=1, ge=0)
    spawn_max_turns: int = Field(default=8, ge=1)
    max_parallel_tool_calls: int = Field(default=3, ge=1)
    subagent_system_prompt: str = Field(
        default=DEFAULT_SUBAGENT_SYSTEM_PROMPT,
        min_length=1,
    )
    context_limits: dict[str, int] = Field(default_factory=default_context_limits)

    @model_validator(mode="before")
    @classmethod
    def _drop_removed_spill_settings(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tool_output_dir" in data:
            data = dict(data)
            data.pop("tool_output_dir", None)
        return data


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


def load_harness_config(path: str | Path) -> HarnessConfig:
    """Load harness settings from a JSON file.

    A shared Symphony file may put these values under ``harness``; a standalone
    harness file may place them at the top level. Omitted keys use the
    ``HarnessConfig`` field defaults. There is no packaged defaults file.
    """
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise ValueError(f"Config file does not exist: {source}")
    payload = _read_json(source)
    override = payload.get("harness", payload)
    if not isinstance(override, dict):
        raise ValueError(f"The harness section in {source} must be a JSON object")
    merged = _merge(HarnessConfig().model_dump(), override)
    return HarnessConfig.model_validate(merged)


def resolve_harness_config(source: SettingsSource) -> HarnessConfig:
    """Accept a loaded ``HarnessConfig`` or a JSON path."""
    if isinstance(source, HarnessConfig):
        return source
    return load_harness_config(source)


__all__ = [
    "DEFAULT_SUBAGENT_SYSTEM_PROMPT",
    "HarnessConfig",
    "SettingsSource",
    "default_context_limits",
    "load_harness_config",
    "resolve_harness_config",
]
