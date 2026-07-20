from typing import Any, Dict

from pydantic import BaseModel, Field


class ControlPlaneEvent(BaseModel):
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
