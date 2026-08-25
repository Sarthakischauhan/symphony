from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from core_ai.types import Content

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