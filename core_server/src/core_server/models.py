"""Supported model metadata and Chat SDK registry response models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

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


class ModelRegistryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default_provider_id: str = Field(alias="defaultProviderId")
    providers: List[RegistryProvider]
