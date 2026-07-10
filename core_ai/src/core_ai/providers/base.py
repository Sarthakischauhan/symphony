from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List

from core_ai.types import Message, StreamEvent


class BaseProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Takes unified messages, translates to provider-specific format,
        and yields unified StreamEvents.
        """
        pass
        # Need a yield statement to make it an async generator for type checkers
        yield StreamEvent(type="done", content_index=0)
