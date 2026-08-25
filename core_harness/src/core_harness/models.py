"""Harness event, tool, and result models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from core_ai.types import Content, Message

# --- tools.py ---
ToolResultStatus = Literal["success", "error", "timeout", "cancelled"]


class PendingToolCall(BaseModel):
    id: str
    name: Optional[str] = None
    arguments_json: str = ""


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result_status: Optional[ToolResultStatus] = None


class ToolResult(BaseModel):
    """Canonical outcome for every tool invocation."""

    status: ToolResultStatus
    content: Content
    error_type: Optional[str] = None

    def for_model(self) -> Content:
        if self.status == "success":
            return self.content
        text = self.content if isinstance(self.content, str) else str(self.content)
        prefix = f"[tool:{self.status}]"
        if self.error_type:
            return f"{prefix} {self.error_type}: {text}"
        return f"{prefix} {text}"

# --- control_plane.py ---
EVENT_SCHEMA_VERSION = 1


class ControlPlaneEventType(str, Enum):
    """Typed catalog of harness control-plane events (string-compatible)."""

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    RUN_LIMIT_EXCEEDED = "run_limit_exceeded"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    USAGE = "usage"
    CONTEXT = "context"
    CONTEXT_WARNING = "context_warning"
    COMPACTION_STARTED = "compaction_started"
    COMPACTION_COMPLETED = "compaction_completed"
    PAUSED = "paused"
    RESUMED = "resumed"
    MESSAGE_INJECTED = "message_injected"


class ControlPlaneEvent(BaseModel):
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def typed(
        cls,
        event_type: Union[ControlPlaneEventType, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> "ControlPlaneEvent":
        name = event_type.value if isinstance(event_type, ControlPlaneEventType) else event_type
        return cls(event_type=name, payload=payload or {})


class ControlCommandType(str, Enum):
    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"
    INJECT_MESSAGE = "inject_message"


class ControlCommand(BaseModel):
    type: ControlCommandType
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def cancel(cls, reason: str = "cancelled") -> "ControlCommand":
        return cls(type=ControlCommandType.CANCEL, payload={"reason": reason})

    @classmethod
    def pause(cls) -> "ControlCommand":
        return cls(type=ControlCommandType.PAUSE)

    @classmethod
    def resume(cls) -> "ControlCommand":
        return cls(type=ControlCommandType.RESUME)

    @classmethod
    def inject_message(
        cls,
        *,
        role: Literal["user", "system"] = "user",
        content: str,
    ) -> "ControlCommand":
        return cls(
            type=ControlCommandType.INJECT_MESSAGE,
            payload={"role": role, "content": content},
        )

    def to_message(self) -> Message:
        if self.type != ControlCommandType.INJECT_MESSAGE:
            raise ValueError("Only inject_message commands can become Message objects.")
        role = self.payload.get("role", "user")
        content = self.payload.get("content", "")
        if role not in ("user", "system"):
            raise ValueError("inject_message role must be 'user' or 'system'.")
        return Message(role=role, content=str(content))

# --- harness.py ---
class UsageTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


class RunLimits(BaseModel):
    """Optional caps for a single harness run."""

    max_turns: int = 8
    max_tool_calls: Optional[int] = None
    max_runtime_seconds: Optional[float] = None
    max_tokens: Optional[int] = None


class HarnessResult(BaseModel):
    output_text: str
    messages: List[Message]
    tool_calls: List[ToolCall] = Field(default_factory=list)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    context_limit: Optional[int] = None
    context_left: Optional[int] = None

__all__ = [
    "ControlCommand",
    "ControlCommandType",
    "ControlPlaneEvent",
    "ControlPlaneEventType",
    "EVENT_SCHEMA_VERSION",
    "HarnessResult",
    "PendingToolCall",
    "RunLimits",
    "ToolCall",
    "ToolResult",
    "UsageTotals",
]
