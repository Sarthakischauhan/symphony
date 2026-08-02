"""Persistence protocol for conversation history and checkpoints."""

from typing import List, Optional, Protocol

from core_ai.types import Message
from core_harness.persistence.checkpoint import Checkpoint


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
