"""Observation and decision types for the browser agent.

Jev never invents an element. Every target is an index into the table the
page snapshot just produced.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

OPERATIONS = (
    "CLICK",
    "TYPE_TEXT",
    "SELECT",
    "SCROLL_DOWN",
    "SCROLL_UP",
    "WAIT",
    "PRESS_ENTER",
    "DONE",
    "BLOCKED",
)

RunStatus = Literal["done", "blocked", "limited", "error"]


class Element(BaseModel):
    index: int
    role: str
    name: str
    value: str = ""
    kind: Literal["click", "type", "select"] = "click"
    options: list[str] = Field(default_factory=list)

    def label(self) -> str:
        bits = f"[{self.index}] {self.role} {self.name}".strip()
        if self.kind == "type":
            bits += f" · {self.value}" if self.value else " · empty"
        elif self.value:
            bits += f" · {self.value}"
        if self.kind == "select" and self.options:
            bits += " · options " + ", ".join(self.options[:6])
        return bits[:180]

    def compact(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "role": self.role,
            "name": self.name,
            "kind": self.kind,
            "value": self.value,
        }
        if self.options:
            payload["options"] = self.options[:12]
        return payload


class Observation(BaseModel):
    url: str
    title: str = ""
    elements: list[Element] = Field(default_factory=list)
    text: str = ""

    def find(self, index: Optional[int]) -> Optional[Element]:
        if index is None:
            return None
        for element in self.elements:
            if element.index == index:
                return element
        return None


class Decision(BaseModel):
    """One Jev (or fixture) answer, already reduced to the operation we run."""

    operation: str
    confidence: float = 0.0
    click_target: Optional[int] = None
    type_target: Optional[int] = None
    type_value: str = ""
    select_index: Optional[int] = None
    select_option: str = ""
    goal_met: bool = False
    goal_met_confidence: float = 0.0
    model: str = ""
    provider: str = ""
    probabilities: dict[str, float] = Field(default_factory=dict)
    reason: str = ""

    def target_index(self) -> Optional[int]:
        if self.operation == "CLICK":
            return self.click_target
        if self.operation in {"TYPE_TEXT", "PRESS_ENTER"}:
            return self.type_target
        if self.operation == "SELECT":
            return self.select_index
        return None

    def signature(self) -> tuple[str, Optional[int], str]:
        return (self.operation, self.target_index(), self.type_value)

    def event_payload(self) -> dict[str, Any]:
        value = self.type_value
        target = self.type_target
        return {
            "source": "browser",
            "model": self.model,
            "provider": self.provider,
            "operation": self.operation,
            "confidence": self.confidence,
            "click_target": self.click_target,
            "type_target": target,
            "type_value": value,
            "select_index": self.select_index,
            "select_option": self.select_option,
            "goal_met": self.goal_met,
            "goal_met_confidence": self.goal_met_confidence,
            "probabilities": self.probabilities,
            "reason": self.reason,
        }


class StepRecord(BaseModel):
    step: int
    operation: str
    target: Optional[int] = None
    type_value: str = ""
    confidence: float = 0.0
    url: str = ""
    note: str = ""


class BrowserRunResult(BaseModel):
    status: RunStatus
    output_text: str = ""
    url: str = ""
    title: str = ""
    goal: str = ""
    model: str = ""
    provider: str = ""
    steps: list[StepRecord] = Field(default_factory=list)
    message: str = ""


__all__ = [
    "OPERATIONS",
    "BrowserRunResult",
    "Decision",
    "Element",
    "Observation",
    "RunStatus",
    "StepRecord",
]
