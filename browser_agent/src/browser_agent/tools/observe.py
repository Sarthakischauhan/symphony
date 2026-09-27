"""Read the current page without changing it."""

from __future__ import annotations

from typing import Any

from browser_agent.session import PageSession
from browser_agent.tools.base import PageTool, render_page

_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}, "required": []}


class ObservePageTool(PageTool):
    def __init__(self, session: PageSession) -> None:
        super().__init__(
            session,
            name="observe_page",
            description="Read the current page: URL, title, numbered elements, and visible text. Changes nothing.",
            parameters=_SCHEMA,
        )

    async def execute(self, *, sink: Any, args: dict[str, Any]) -> str:
        del sink, args
        try:
            return render_page(await self.session.observe())
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
