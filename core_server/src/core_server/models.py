"""Supported model metadata and Chat SDK registry response models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core_harness.models import (
    ControlPlaneEvent,
    ControlPlaneEventType,
    HarnessResult,
    PendingToolCall,
    RunLimits,
    ToolCall,
    ToolResult,
    UsageTotals,
)

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class SupportedModel:
    """A model slug accepted by ``POST /runs`` and shown in the client."""

    slug: str
    label: str = ""

    def __post_init__(self) -> None:
        slug = self.slug.strip()
        if not slug:
            raise ValueError("model slug must not be empty")
        object.__setattr__(self, "slug", slug)
        object.__setattr__(self, "label", self.label.strip() or slug)


class RegistryModel(BaseModel):
    id: str
    label: str


class RegistryProvider(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    default_model: str = Field(alias="defaultModel")
    models: List[RegistryModel]


class StreamedTurn(BaseModel):
    assistant_text: str = ""
    reasoning_texts: Dict[int, str] = Field(default_factory=dict)
    pending_calls: Dict[int, PendingToolCall] = Field(default_factory=dict)
    saw_usage: bool = False
    attempt_usage: UsageTotals = Field(default_factory=UsageTotals)
    budget_tokens: int = 0
    estimated_message_tokens: int = 0


class TurnResult(BaseModel):
    assistant_text: str
    tool_calls: List[ToolCall]
    usage: UsageTotals
    budget_tokens: int
    context_left: Optional[int]
    message_sizes: List[Dict[str, Any]]


class ModelRegistryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default_provider_id: str = Field(alias="defaultProviderId")
    providers: List[RegistryProvider]


__all__ = [
    "ControlPlaneEvent",
    "ControlPlaneEventType",
    "HarnessResult",
    "ModelRegistryResponse",
    "PendingToolCall",
    "RegistryModel",
    "RegistryProvider",
    "RunLimits",
    "StreamedTurn",
    "SupportedModel",
    "ToolCall",
    "ToolResult",
    "TurnResult",
    "UsageTotals",
]
