"""Persistence add-on: protocol, checkpoint, and the no-op store."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field

from core_ai.types import Message
from core_harness.addons.addon import Addon
from core_harness.events import EventLog
from core_harness.models import UsageTotals

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


class Persistence(EventLog, Protocol):
    """Conversations, checkpoints, and the event journal."""

    async def save_conversation(self, *, session_id: str, messages: List[Message]) -> None:
        ...

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        ...

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        ...

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        ...

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        ...


class NullPersistence:
    """Discard conversations, checkpoints, and journal events."""

    async def save_conversation(self, *, session_id: str, messages: List[Message]) -> None:
        return None

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        return []

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        return None

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        return None

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        del event_type, payload
        return None


class PersistenceAddon(Addon):
    """Mount a ``Persistence`` store onto a harness.

    The store is conversations, checkpoints, and ``append_event``.
    ``fork_for_child`` returns ``None`` so children keep ``NullPersistence``
    unless ``ChildConfig`` passes add-ons or a factory.
    """

    name = "persistence"

    def __init__(self, store: Persistence | None = None) -> None:
        self.store = store or NullPersistence()

    def attach(self, harness: Any) -> None:
        harness.persistence = self.store

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None


__all__ = [
    "Checkpoint",
    "CheckpointStatus",
    "NullPersistence",
    "Persistence",
    "PersistenceAddon",
]
