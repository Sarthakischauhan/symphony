"""Persistence protocol for conversation history and run checkpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.models.harness import UsageTotals


CheckpointStatus = Literal["running", "completed", "failed", "cancelled"]


class Checkpoint(BaseModel):
    """Snapshot of harness state at a turn boundary or run end."""

    session_id: str
    turn: int
    messages: List[Message] = Field(default_factory=list)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    context_limit: Optional[int] = None
    context_left: Optional[int] = None
    status: CheckpointStatus = "running"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Persistence(Protocol):
    """Pluggable store for conversations and checkpoints."""

    async def save_conversation(
        self,
        *,
        session_id: str,
        messages: List[Message],
    ) -> None:
        """Persist the full message list for a session."""

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        """Load prior messages for a session (empty if unknown)."""

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        """Persist a turn/run checkpoint."""

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        """Load the latest checkpoint for a session, if any."""


class NullPersistence:
    """No-op default persistence."""

    async def save_conversation(
        self,
        *,
        session_id: str,
        messages: List[Message],
    ) -> None:
        return None

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        return []

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        return None

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        return None
