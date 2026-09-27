"""Scroll the page up or down."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool

_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}, "required": []}


class ScrollTool(PageTool):
    def __init__(self, session: PageSession, *, down: bool) -> None:
        name = "scroll_down" if down else "scroll_up"
        super().__init__(
            session,
            name=name,
            description="Scroll the page down to reveal more." if down else "Scroll the page up.",
            parameters=_SCHEMA,
        )
        self._operation = "SCROLL_DOWN" if down else "SCROLL_UP"

    def decision(self, args: dict[str, Any]) -> Decision:
        del args
        return Decision(operation=self._operation)
