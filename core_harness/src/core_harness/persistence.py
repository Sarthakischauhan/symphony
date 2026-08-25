"""Persistence protocol, checkpoint model, and the no-op store."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.models import UsageTotals

# --- checkpoint.py ---
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

# --- base.py ---
class Persistence(Protocol):
    """Pluggable store for conversations and run checkpoints."""

    async def save_conversation(self, *, session_id: str, messages: List[Message]) -> None:
        ...

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        ...

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        ...

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        ...

# --- null.py ---
class NullPersistence:
    """Discard conversations and checkpoints."""

    async def save_conversation(self, *, session_id: str, messages: List[Message]) -> None:
        return None

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        return []

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        return None

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        return None

__all__ = ["Checkpoint", "CheckpointStatus", "NullPersistence", "Persistence"]
