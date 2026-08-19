from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

from core_ai.types import Message, StreamEvent


class BaseProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Takes unified messages, translates to provider-specific format,
        and yields unified StreamEvents.
        """
        pass
        # Need a yield statement to make it an async generator for type checkers
        yield StreamEvent(type="done", content_index=0)
