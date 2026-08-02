"""No-op persistence implementation used as the default."""

from typing import List, Optional

from core_ai.types import Message
from core_harness.persistence.checkpoint import Checkpoint


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
