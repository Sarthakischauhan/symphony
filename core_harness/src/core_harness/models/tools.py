from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PendingToolCall(BaseModel):
    id: str
    name: Optional[str] = None
    arguments_json: str = ""


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
