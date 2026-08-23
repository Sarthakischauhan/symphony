from dataclasses import dataclass
from typing import Literal

ModelAPI = Literal["responses", "chat_completions", "messages", "generate_content"]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    api: ModelAPI

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"
