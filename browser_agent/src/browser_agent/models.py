"""What one page snapshot contains, and what one browser run returns."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Operation = Literal["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_DOWN", "SCROLL_UP", "WAIT", "PRESS_ENTER"]
RunStatus = Literal["done", "blocked", "limited", "error"]


class Element(BaseModel):
    """One interactive node from the page snapshot, addressed by ``index``.

    ``secret`` is set by the page itself (``type=password`` or a credential
    ``autocomplete`` token). A filled secret carries ``***``, never its value.
    """

    index: int
    role: str
    name: str
    value: str = ""
    kind: Literal["click", "type", "select"] = "click"
    options: list[str] = Field(default_factory=list)
    secret: bool = False


class Observation(BaseModel):
    """What a tool sees of the page after one action."""

    url: str
    title: str = ""
    elements: list[Element] = Field(default_factory=list)
    text: str = ""

    def find(self, index: Optional[int]) -> Optional[Element]:
        """The element with ``index``, or None when this page has no such element."""
        return next((element for element in self.elements if element.index == index), None)


class Decision(BaseModel):
    """One browser operation a tool asks the page to run."""

    operation: Operation
    click_target: Optional[int] = None
    type_target: Optional[int] = None
    type_value: str = ""
    select_index: Optional[int] = None
    select_option: str = ""

    def target_index(self) -> Optional[int]:
        """The element index the operation acts on, if it acts on one."""
        if self.operation == "CLICK":
            return self.click_target
        if self.operation in {"TYPE_TEXT", "PRESS_ENTER"}:
            return self.type_target
        if self.operation == "SELECT":
            return self.select_index
        return None


class BrowserRunResult(BaseModel):
    """The outcome of one ``BrowserAgent.run``."""

    status: RunStatus
    output_text: str = ""
    goal: str = ""
    model: str = ""
    provider: str = ""
    message: str = ""


__all__ = [
    "BrowserRunResult",
    "Decision",
    "Element",
    "Observation",
    "Operation",
    "RunStatus",
]
