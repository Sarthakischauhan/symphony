from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

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
    content: str
    error_type: Optional[str] = None

    def for_model(self) -> str:
        if self.status == "success":
            return self.content
        prefix = f"[tool:{self.status}]"
        if self.error_type:
            return f"{prefix} {self.error_type}: {self.content}"
        return f"{prefix} {self.content}"
