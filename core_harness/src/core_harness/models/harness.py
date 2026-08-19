from typing import List, Optional

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.models.tools import ToolCall


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
