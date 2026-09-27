"""Choose an option in a dropdown."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool, index_of


class SelectTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="select_option",
            description="Choose an option in a dropdown by its visible label.",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer", "description": "Dropdown index."},
                    "option": {"type": "string", "description": "Visible option label."},
                },
                "required": ["index", "option"],
            },
        )

    def decision(self, args: dict[str, Any]) -> Decision:
        return Decision(operation="SELECT", select_index=index_of(args), select_option=str(args.get("option") or ""))
