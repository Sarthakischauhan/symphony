"""One browser operation. Every tool of a run shares the same page."""

from __future__ import annotations

import re
from typing import Any, Optional

from core_harness import Tool

from browser_agent.models import Decision, Element, Observation
from browser_agent.session import PageSession
from browser_agent.urls import require_http_url

_SECRET_NAME = re.compile(r"password|passcode|secret|\botp\b|\bpin\b|cvv|card", re.IGNORECASE)


def render_page(observation: Observation) -> str:
    """The page as the model reads it back from a tool result.

    A filled secret field, or a field whose name says it holds a password,
    PIN, OTP, or card, is shown as ``***``. The typed value never comes back.
    """
    lines = [f"URL: {observation.url}", f"Title: {observation.title}"]
    if observation.elements:
        lines.append("Elements:")
        lines.extend(f"  {label(element)}" for element in observation.elements)
    else:
        lines.append("Elements: none")
    lines.append("Page text:")
    lines.append(observation.text[:4000] or "(empty)")
    return "\n".join(lines)


def label(element: Element) -> str:
    """One line, e.g. ``[1] textbox Search · empty``."""
    bits = f"[{element.index}] {element.role} {element.name}".strip()
    shown = shown_value(element)
    if shown or element.kind == "type":
        bits += f" · {shown or 'empty'}"
    if element.kind == "select" and element.options:
        bits += " · options " + ", ".join(element.options[:6])
    return bits[:180]


def shown_value(element: Element) -> str:
    """``***`` for a filled secret; the real value otherwise."""
    if element.value and (element.secret or _named_secret(element.name)):
        return "***"
    return element.value


def _named_secret(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def index_of(args: dict[str, Any]) -> Optional[int]:
    """The integer ``index`` argument, or None when the model omitted it."""
    raw = args.get("index")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return int(raw)


class PageTool(Tool):
    """Acts on the shared page, then returns the new snapshot."""

    def __init__(self, session: PageSession, *, name: str, description: str, parameters: dict[str, Any]) -> None:
        super().__init__(name=name, description=description, parameters=parameters)
        self.session = session

    async def execute(self, *, sink: Any, args: dict[str, Any]) -> str:
        del sink
        try:
            require_http_url((await self.session.observe()).url)
            await self.session.act(self.decision(args))
            return render_page(await self.session.observe())
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    def decision(self, args: dict[str, Any]) -> Decision:
        raise NotImplementedError
