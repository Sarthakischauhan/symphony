"""Replace the contents of a text field."""

from __future__ import annotations

from typing import Any

from browser_agent.models import Decision
from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool, index_of


class TypeTextTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="type_text",
            description="Replace the contents of a text field with this exact string.",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer", "description": "Field index."},
                    "text": {"type": "string", "description": "The exact string to type."},
                },
                "required": ["index", "text"],
            },
        )

    def decision(self, args: dict[str, Any]) -> Decision:
        return Decision(operation="TYPE_TEXT", type_target=index_of(args), type_value=str(args.get("text") or ""))
