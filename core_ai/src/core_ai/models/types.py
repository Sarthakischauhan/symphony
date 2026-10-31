from dataclasses import dataclass
from typing import Literal

ModelAPI = Literal["responses", "chat_completions", "messages", "generate_content"]
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ThinkingLevelMap = tuple[tuple[ThinkingLevel, str | None], ...]


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per million tokens. Missing cache rates fall back to the input rate."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    api: ModelAPI
    reasoning: bool = False
    thinking_level_map: ThinkingLevelMap = ()
    context_limit: int | None = None
    price: ModelPrice | None = None

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"
