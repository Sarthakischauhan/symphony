"""Observation and decision types for the browser agent.

Jev never invents an element. Every target is an index into the table the
page snapshot just produced.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from browser_agent.redact_secret_fields import is_secret_field

Operation = Literal[
    "CLICK", "TYPE_TEXT", "SELECT", "SCROLL_DOWN", "SCROLL_UP", "WAIT", "PRESS_ENTER", "DONE", "BLOCKED"
]
RunStatus = Literal["done", "blocked", "limited", "error"]


class Element(BaseModel):
    """One interactive node from the page snapshot, addressed by ``index``.

    ``secret`` is set by the page itself (``type=password`` or a credential
    ``autocomplete`` token). The snapshot never carries a secret's value.
    """

    index: int
    role: str
    name: str
    value: str = ""
    kind: Literal["click", "type", "select"] = "click"
    options: list[str] = Field(default_factory=list)
    secret: bool = False

    @property
    def shown_value(self) -> str:
        """The value Jev may see: ``***`` for a filled secret field."""
        return "***" if self.value and is_secret_field(self) else self.value

    def label(self) -> str:
        """One line of Jev criteria text, e.g. ``[1] textbox Search · empty``."""
        bits = f"[{self.index}] {self.role} {self.name}".strip()
        if self.shown_value or self.kind == "type":
            bits += f" · {self.shown_value or 'empty'}"
        if self.kind == "select" and self.options:
            bits += " · options " + ", ".join(self.options[:6])
        return bits[:180]

    def compact(self) -> dict[str, Any]:
        """The element as it appears in Jev's ``state.elements``."""
        payload = self.model_dump(include={"index", "role", "name", "kind"}) | {"value": self.shown_value}
        if self.options:
            payload["options"] = self.options
        return payload


class Observation(BaseModel):
    """What the agent sees of the page for one step."""

    url: str
    title: str = ""
    elements: list[Element] = Field(default_factory=list)
    text: str = ""

    def find(self, index: Optional[int]) -> Optional[Element]:
        """The element with ``index``, or None when this page has no such element."""
        return next((element for element in self.elements if element.index == index), None)


class Decision(BaseModel):
    """One Jev (or fixture) answer, already reduced to the operation we run."""

    operation: Operation
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
        """The element index the chosen operation acts on, if it acts on one."""
        if self.operation == "CLICK":
            return self.click_target
        if self.operation in {"TYPE_TEXT", "PRESS_ENTER"}:
            return self.type_target
        if self.operation == "SELECT":
            return self.select_index
        return None

    def event_payload(self) -> dict[str, Any]:
        """The ``jev_decision`` event body. Callers redact ``type_value`` first."""
        return self.model_dump() | {"source": "browser"}


class StepRecord(BaseModel):
    """One executed (or terminal) step in the run result."""

    step: int
    operation: Operation
    target: Optional[int] = None
    type_value: str = ""
    confidence: float = 0.0
    url: str = ""
    note: str = ""


class BrowserRunResult(BaseModel):
    """The outcome of one ``BrowserAgent.run``."""

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
    "BrowserRunResult",
    "Decision",
    "Element",
    "Observation",
    "Operation",
    "RunStatus",
    "StepRecord",
]
