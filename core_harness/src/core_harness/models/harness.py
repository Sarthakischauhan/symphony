from typing import List

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.models.tools import ToolCall


class HarnessResult(BaseModel):
    output_text: str
    messages: List[Message]
    tool_calls: List[ToolCall] = Field(default_factory=list)
