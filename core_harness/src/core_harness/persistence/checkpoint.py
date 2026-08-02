"""Checkpoint model used to persist a harness run boundary."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.models.harness import UsageTotals


CheckpointStatus = Literal["running", "completed", "failed", "cancelled"]


class Checkpoint(BaseModel):
    """Snapshot of messages, usage, context, and terminal status."""

    session_id: str
    turn: int
    messages: List[Message] = Field(default_factory=list)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    context_limit: Optional[int] = None
    context_left: Optional[int] = None
    status: CheckpointStatus = "running"
    metadata: Dict[str, Any] = Field(default_factory=dict)
