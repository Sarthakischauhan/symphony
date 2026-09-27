"""Press Enter on a text field to submit it."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool, index_of


class PressEnterTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="press_enter",
            description="Press Enter on a text field to submit it.",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"index": {"type": "integer", "description": "Field index."}},
                "required": ["index"],
            },
        )

    def decision(self, args: dict[str, Any]) -> Decision:
        return Decision(operation="PRESS_ENTER", type_target=index_of(args))
