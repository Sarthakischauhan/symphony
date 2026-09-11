"""Server-side harness configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_harness import (
    Addon,
    HarnessConfig,
    Persistence,
    PersistenceAddon,
    SubagentAddon,
    Tool,
    compaction_from_config,
)

from core_server.models import SupportedModel

DEFAULT_SYSTEM_PROMPT = "You are a helpful agent."


@dataclass
class ServerConfig:
    """Values used to construct a CoreHarness for each run."""

    registry: ModelRegistry
    model_id: str
    supported_models: List[SupportedModel] = field(default_factory=list)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    tools: List[Tool] = field(default_factory=list)
    persistence: Optional[Persistence] = None
    addons: List[Addon] = field(default_factory=list)
    enable_subagents: bool = False
    reasoning_effort: Optional[str] = None
    max_turns: int = 8
    max_tool_calls: Optional[int] = None
    max_runtime_seconds: Optional[float] = None
    max_tokens: Optional[int] = None
    context_limits: Optional[Dict[str, int]] = None
    context_warn_threshold: Optional[int] = None
    context_compact_threshold: Optional[int] = None
    tool_result_max_chars: Optional[int] = 4_000
    tool_result_keep_recent: int = 8
    tool_result_prune_tokens: Optional[int] = None
    context_target_tokens: Optional[int] = None
    compaction_keep_recent: int = 10
    max_spawn_depth: int = 1
    spawn_max_turns: int = 8
    max_parallel_tool_calls: int = 3
    cors_origins: List[str] = field(default_factory=list)
    max_request_bytes: int = 1_048_576
    max_message_chars: int = 32_000
    max_history_messages: int = 100
    max_history_chars: int = 500_000
    sse_queue_size: int = 256
    disconnect_cancel_timeout: float = 5.0

    def __post_init__(self) -> None:
        self.supported_models = list(self.supported_models)
        if not self.supported_models:
            self.supported_models = [SupportedModel(self.model_id)]
        slugs = [model.slug for model in self.supported_models]
        if len(slugs) != len(set(slugs)):
            raise ValueError("supported model slugs must be unique")
        if self.model_id not in slugs:
            raise ValueError("model_id must be present in supported_models")

        positive = {
            "max_turns": self.max_turns,
            "compaction_keep_recent": self.compaction_keep_recent,
            "spawn_max_turns": self.spawn_max_turns,
            "max_parallel_tool_calls": self.max_parallel_tool_calls,
            "max_request_bytes": self.max_request_bytes,
            "max_message_chars": self.max_message_chars,
            "max_history_messages": self.max_history_messages,
            "max_history_chars": self.max_history_chars,
            "sse_queue_size": self.sse_queue_size,
            "disconnect_cancel_timeout": self.disconnect_cancel_timeout,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_spawn_depth < 0:
            raise ValueError("max_spawn_depth must be non-negative")
        if self.tool_result_keep_recent < 0:
            raise ValueError("tool_result_keep_recent must be non-negative")

    def to_harness_config(self) -> HarnessConfig:
        """Settings object passed to ``CoreHarness`` for each run."""
        values: dict = {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_tokens": self.max_tokens,
            "context_warn_threshold": self.context_warn_threshold,
            "context_compact_threshold": self.context_compact_threshold,
            "tool_result_max_chars": self.tool_result_max_chars,
            "tool_result_keep_recent": self.tool_result_keep_recent,
            "tool_result_prune_tokens": self.tool_result_prune_tokens,
            "context_target_tokens": self.context_target_tokens,
            "compaction_keep_recent": self.compaction_keep_recent,
            "max_spawn_depth": self.max_spawn_depth,
            "spawn_max_turns": self.spawn_max_turns,
            "max_parallel_tool_calls": self.max_parallel_tool_calls,
        }
        if self.context_limits is not None:
            values["context_limits"] = self.context_limits
        return HarnessConfig(**values)

    def addons_for_run(self) -> list[Addon]:
        """Persistence, compaction, and spawn add-ons for one ``CoreHarness``."""
        addons: list[Addon] = []
        if self.persistence is not None:
            addons.append(PersistenceAddon(self.persistence))
        if (
            self.context_compact_threshold is not None
            or self.context_target_tokens is not None
        ):
            addons.append(compaction_from_config(self.to_harness_config()))
        if self.enable_subagents:
            addons.append(SubagentAddon())
        addons.extend(self.addons)
        return addons

    def model_facing_tool_names(self) -> list[str]:
        names = [tool.name for tool in self.tools]
        if self.enable_subagents and "spawn_agent" not in names:
            names.append("spawn_agent")
        return names


def build_config(
    *,
    registry: Optional[ModelRegistry] = None,
    model_id: Optional[str] = None,
    supported_models: Optional[List[SupportedModel]] = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    tools: Optional[List[Tool]] = None,
    persistence: Optional[Persistence] = None,
    addons: Optional[List[Addon]] = None,
    enable_subagents: bool = False,
    reasoning_effort: Optional[str] = None,
    max_turns: int = 8,
    max_tool_calls: Optional[int] = None,
    max_runtime_seconds: Optional[float] = None,
    max_tokens: Optional[int] = None,
    cors_origins: Optional[List[str]] = None,
    max_request_bytes: int = 1_048_576,
    max_message_chars: int = 32_000,
    max_history_messages: int = 100,
    max_history_chars: int = 500_000,
    sse_queue_size: int = 256,
    disconnect_cancel_timeout: float = 5.0,
    context_limits: Optional[Dict[str, int]] = None,
    context_warn_threshold: Optional[int] = None,
    context_compact_threshold: Optional[int] = None,
    tool_result_max_chars: Optional[int] = 4_000,
    tool_result_keep_recent: int = 8,
    tool_result_prune_tokens: Optional[int] = None,
    context_target_tokens: Optional[int] = None,
    compaction_keep_recent: int = 10,
    max_spawn_depth: int = 1,
    spawn_max_turns: int = 8,
    max_parallel_tool_calls: int = 3,
) -> ServerConfig:
    """Build a server config from explicit values or the process environment."""
    resolved_model = (
        model_id
        or os.getenv("SYMPHONY_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("GEMINI_MODEL")
        or os.getenv("GROK_MODEL")
        or os.getenv("XAI_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or os.getenv("LOCAL_MODEL")
        or "gpt-5.6-luna"
    )
    if ":" not in resolved_model:
        resolved_model = _qualify_model(resolved_model)
    return ServerConfig(
        registry=registry if registry is not None else _default_registry(),
        model_id=resolved_model,
        supported_models=list(supported_models or []),
        system_prompt=system_prompt,
        tools=list(tools or []),
        persistence=persistence,
        addons=list(addons or []),
        enable_subagents=enable_subagents,
        reasoning_effort=reasoning_effort,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_runtime_seconds=max_runtime_seconds,
        max_tokens=max_tokens,
        cors_origins=list(cors_origins or []),
        max_request_bytes=max_request_bytes,
        max_message_chars=max_message_chars,
        max_history_messages=max_history_messages,
        max_history_chars=max_history_chars,
        sse_queue_size=sse_queue_size,
        disconnect_cancel_timeout=disconnect_cancel_timeout,
        context_limits=context_limits,
        context_warn_threshold=context_warn_threshold,
        context_compact_threshold=context_compact_threshold,
        tool_result_max_chars=tool_result_max_chars,
        tool_result_keep_recent=tool_result_keep_recent,
        tool_result_prune_tokens=tool_result_prune_tokens,
        context_target_tokens=context_target_tokens,
        compaction_keep_recent=compaction_keep_recent,
        max_spawn_depth=max_spawn_depth,
        spawn_max_turns=spawn_max_turns,
        max_parallel_tool_calls=max_parallel_tool_calls,
    )


def _qualify_model(model_name: str) -> str:
    if model_name.startswith("claude-"):
        return f"anthropic:{model_name}"
    if model_name.startswith("gemini-"):
        return f"gemini:{model_name}"
    if model_name.startswith("grok-"):
        return f"grok:{model_name}"
    return f"openai:{model_name}"


def _default_registry() -> ModelRegistry:
    from core_ai.providers.defaults import build_default_registry

    return build_default_registry()
