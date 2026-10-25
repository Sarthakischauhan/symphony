"""The model-turn interface the harness streams from."""

from collections.abc import AsyncGenerator
from typing import Any, Dict, List, Optional, Protocol

from core_ai.types import Message, StreamEvent


class ModelCall(Protocol):
    """``core_ai.ModelRegistry`` satisfies it; so does ``VoiceModelCall``."""

    def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = ...,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]: ...
