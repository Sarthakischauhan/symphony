"""JSON-backed configuration owned by the harness engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class HarnessConfig(BaseModel):
    """Runtime limits and policies that belong to ``core_harness``."""

    model_config = ConfigDict(extra="forbid")

    max_turns: int = Field(ge=1)
    max_tool_calls: Optional[int] = Field(default=None, ge=1)
    max_runtime_seconds: Optional[float] = Field(default=None, gt=0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    tool_result_max_chars: Optional[int] = Field(default=None, ge=1)
    context_warn_threshold: Optional[int] = Field(default=None, ge=0)
    context_compact_threshold: Optional[int] = Field(default=None, ge=0)
    context_target_tokens: Optional[int] = Field(default=None, ge=1)
    compaction_keep_recent: int = Field(ge=1)
    max_spawn_depth: int = Field(ge=0)
    spawn_max_turns: int = Field(ge=1)
    max_parallel_tool_calls: int = Field(ge=1)
    subagent_system_prompt: str = Field(min_length=1)
    context_limits: dict[str, int] = Field(default_factory=dict)


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


DEFAULT_CONFIG_PATH = Path(__file__).with_name("defaults.json")
DEFAULT_HARNESS_CONFIG = HarnessConfig.model_validate(_read_json(DEFAULT_CONFIG_PATH))


def load_harness_config(path: str | Path | None = None) -> HarnessConfig:
    """Load harness defaults, optionally overlaid by a JSON file.

    A shared Symphony file may put these values under ``harness``; a standalone
    harness file may place them at the top level.
    """
    if path is None:
        return DEFAULT_HARNESS_CONFIG.model_copy(deep=True)
    source = Path(path).expanduser().resolve()
    payload = _read_json(source)
    override = payload.get("harness", payload)
    if not isinstance(override, dict):
        raise ValueError(f"The harness section in {source} must be a JSON object")
    merged = _merge(DEFAULT_HARNESS_CONFIG.model_dump(), override)
    return HarnessConfig.model_validate(merged)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_HARNESS_CONFIG",
    "HarnessConfig",
    "load_harness_config",
]
