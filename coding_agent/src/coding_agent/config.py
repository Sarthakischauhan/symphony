"""Product configuration loaded from packaged and workspace JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core_harness.config import DEFAULT_HARNESS_CONFIG, HarnessConfig


class ApprovalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["ask", "always_allow"] = "ask"
    allow_answers: set[str] = Field(default_factory=set)
    broad_patch_chars: int = Field(ge=1)
    require_for_bash: bool = True
    require_for_overwrite: bool = True
    require_for_broad_patch: bool = True


class BashConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_timeout_seconds: int = Field(ge=1)
    max_timeout_seconds: int = Field(ge=1)
    max_output_bytes: int = Field(ge=1)


class ReadFileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_text_bytes: int = Field(ge=1)
    max_image_bytes: int = Field(ge=1)


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_max_results: int = Field(ge=1)
    default_max_line_chars: int = Field(ge=1)
    binary_sniff_bytes: int = Field(ge=1)


class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bash: BashConfig
    read_file: ReadFileConfig
    search: SearchConfig


class LearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_output_tokens: int = Field(ge=1)
    max_lessons: int = Field(ge=1)
    context_limit: int = Field(ge=1)
    context_max_chars: int = Field(ge=1)


class CodingAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness: HarnessConfig
    approvals: ApprovalConfig
    tools: ToolsConfig
    learning: LearningConfig


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
_PRODUCT_DEFAULTS = _read_json(DEFAULT_CONFIG_PATH)
_PRODUCT_DEFAULTS["harness"] = _merge(
    DEFAULT_HARNESS_CONFIG.model_dump(),
    dict(_PRODUCT_DEFAULTS.get("harness") or {}),
)
DEFAULT_CODING_AGENT_CONFIG = CodingAgentConfig.model_validate(_PRODUCT_DEFAULTS)


def load_coding_agent_config(
    workspace: str | Path | None = None,
    *,
    path: str | Path | None = None,
) -> CodingAgentConfig:
    """Load defaults and overlay ``.symphony/config.json`` when present."""
    source: Optional[Path]
    if path is not None:
        source = Path(path).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"Config file does not exist: {source}")
    elif workspace is not None:
        source = Path(workspace).expanduser().resolve() / ".symphony" / "config.json"
        if not source.exists():
            source = None
    else:
        source = None

    payload = DEFAULT_CODING_AGENT_CONFIG.model_dump(mode="json")
    if source is not None:
        payload = _merge(payload, _read_json(source))
    config = CodingAgentConfig.model_validate(payload)
    if config.tools.bash.default_timeout_seconds > config.tools.bash.max_timeout_seconds:
        raise ValueError(
            "tools.bash.default_timeout_seconds cannot exceed max_timeout_seconds"
        )
    return config


__all__ = [
    "ApprovalConfig",
    "CodingAgentConfig",
    "DEFAULT_CODING_AGENT_CONFIG",
    "DEFAULT_CONFIG_PATH",
    "LearningConfig",
    "ToolsConfig",
    "load_coding_agent_config",
]
