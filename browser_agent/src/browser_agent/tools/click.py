"""Click one element from the latest snapshot."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool, index_of


class ClickTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="click",
            description="Click the element with this index from the latest snapshot.",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"index": {"type": "integer", "description": "Element index, e.g. 2."}},
                "required": ["index"],
            },
        )

    def decision(self, args: dict[str, Any]) -> Decision:
        return Decision(operation="CLICK", click_target=index_of(args))
