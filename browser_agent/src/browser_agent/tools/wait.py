"""Wait briefly for the page to finish updating."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool

_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}, "required": []}


class WaitTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="wait",
            description="Wait briefly for the page to finish updating, then read it again.",
            parameters=_SCHEMA,
        )

    def decision(self, args: dict[str, Any]) -> Decision:
        del args
        return Decision(operation="WAIT")
