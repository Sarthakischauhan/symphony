"""Mutable TUI run state derived from harness control-plane events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

Phase = Literal["idle", "thinking", "streaming", "tool", "paused"]


@dataclass
class RunMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cumulative_tokens: int = 0
    estimated: bool = False
    context_limit: Optional[int] = None
    context_left: Optional[int] = None
    tokens_used: int = 0
    utilization: Optional[float] = None


@dataclass
class UiRunState:
    """Tracks live streaming + metrics for the status/live panes."""

    phase: Phase = "idle"
    model_id: str = ""
    turn: Optional[int] = None
    stream_text: str = ""
    reasoning_text: str = ""
    stream_started: bool = False
    tool_args_preview: str = ""
    metrics: RunMetrics = field(default_factory=RunMetrics)
    detail: str = ""

    def reset_for_run(self, *, model_id: str = "") -> None:
        self.phase = "thinking"
        self.model_id = model_id or self.model_id
        self.turn = None
        self.stream_text = ""
        self.reasoning_text = ""
        self.stream_started = False
        self.tool_args_preview = ""
        self.metrics = RunMetrics()
        self.detail = "starting"

    def begin_turn(self, turn: int) -> None:
        self.turn = turn
        self.phase = "thinking"
        self.stream_text = ""
        self.reasoning_text = ""
        self.stream_started = False
        self.tool_args_preview = ""
        self.detail = f"turn {turn}"

    def append_text(self, delta: str) -> None:
        self.phase = "streaming"
        self.stream_started = True
        self.stream_text += delta
        self.detail = "streaming"

    def append_reasoning(self, delta: str) -> None:
        self.phase = "thinking"
        self.reasoning_text += delta
        self.detail = "reasoning"

    def update_usage(self, payload: Dict[str, Any]) -> None:
        m = self.metrics
        m.prompt_tokens = int(payload.get("prompt_tokens") or 0)
        m.completion_tokens = int(payload.get("completion_tokens") or 0)
        m.reasoning_tokens = int(payload.get("reasoning_tokens") or 0)
        m.total_tokens = int(payload.get("total_tokens") or 0)
        m.cumulative_tokens = int(payload.get("cumulative_tokens") or m.total_tokens)
        m.estimated = bool(payload.get("estimated", False))

    def update_context(self, payload: Dict[str, Any]) -> None:
        m = self.metrics
        limit = payload.get("context_limit")
        left = payload.get("context_left")
        used = payload.get("tokens_used")
        m.context_limit = int(limit) if limit is not None else None
        m.context_left = int(left) if left is not None else None
        m.tokens_used = int(used) if used is not None else m.tokens_used
        util = payload.get("utilization")
        m.utilization = float(util) if util is not None else None

    def status_line(self, *, workspace: str = "") -> str:
        m = self.metrics
        parts: list[str] = []
        if self.model_id:
            parts.append(f"model={self.model_id}")
        if workspace:
            parts.append(f"ws={workspace}")
        parts.append(f"phase={self.phase}")
        if self.detail:
            parts.append(self.detail)

        tokens = m.tokens_used or m.total_tokens
        est = "~" if m.estimated and tokens else ""
        parts.append(f"tokens={est}{tokens}")

        if m.context_limit is not None:
            left = m.context_left if m.context_left is not None else "?"
            parts.append(f"context_left={left}/{m.context_limit}")
        elif m.context_left is not None:
            parts.append(f"context_left={m.context_left}")

        return "  ·  ".join(parts)

    def live_line(self) -> str:
        if self.phase == "streaming" and self.stream_text:
            return f"assistant> {self.stream_text}"
        if self.phase == "tool":
            preview = self.tool_args_preview
            return f"thinking · tool {preview}".rstrip()
        if self.phase == "thinking":
            return "thinking…"
        if self.phase == "paused":
            return "paused"
        return ""
