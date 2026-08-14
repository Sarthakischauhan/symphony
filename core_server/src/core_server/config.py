"""Server-side harness configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_harness.persistence import Persistence
from core_harness.tools import Tool

DEFAULT_SYSTEM_PROMPT = "You are a helpful agent."


@dataclass
class ServerConfig:
    """Values used to construct a CoreHarness for each run."""

    registry: ModelRegistry
    model_id: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    tools: List[Tool] = field(default_factory=list)
    persistence: Optional[Persistence] = None
    max_turns: int = 8
    context_limits: Optional[Dict[str, int]] = None
    context_warn_threshold: Optional[int] = None
    context_compact_threshold: Optional[int] = None
    tool_result_max_chars: Optional[int] = 12_000
    context_target_tokens: Optional[int] = None
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


def build_config(
    *,
    registry: Optional[ModelRegistry] = None,
    model_id: Optional[str] = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    tools: Optional[List[Tool]] = None,
    persistence: Optional[Persistence] = None,
    max_turns: int = 8,
    cors_origins: Optional[List[str]] = None,
) -> ServerConfig:
    """Build a server config from explicit values or the process environment."""
    resolved_model = model_id or os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    if ":" not in resolved_model:
        resolved_model = f"openai:{resolved_model}"
    return ServerConfig(
        registry=registry if registry is not None else _default_registry(),
        model_id=resolved_model,
        system_prompt=system_prompt,
        tools=list(tools or []),
        persistence=persistence,
        max_turns=max_turns,
        cors_origins=list(cors_origins or ["*"]),
    )


def _default_registry() -> ModelRegistry:
    from core_ai import ModelRegistry as Registry
    from core_ai.providers.openai import OpenAIProvider

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    registry = Registry()
    registry.register("openai", OpenAIProvider(api_key=api_key, base_url=base_url))
    return registry
