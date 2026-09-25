"""Free text is the only step that is not a Jev choice.

If the goal already contains the string (a quote, or "search for …"), Jev
picks it as ``type_value`` and this module is not called. Otherwise a small
chat model writes one string. Grok is the default when ``XAI_API_KEY`` is set.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, Protocol

from browser_agent.models import Element, Observation


class TextUnavailable(RuntimeError):
    pass


class TextWriter(Protocol):
    async def write(self, *, goal: str, element: Element, observation: Observation) -> str:
        ...


class StaticTextWriter:
    def __init__(self, text: str) -> None:
        self.text = text

    async def write(self, *, goal: str, element: Element, observation: Observation) -> str:
        del goal, element, observation
        return self.text


def _parse_text(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return payload["text"].strip()
    line = stripped.splitlines()[0].strip().strip('"')
    return line[:200]


class GrokTextWriter:
    """One short Grok completion. Not used to choose the element or the operation."""

    def __init__(self, *, api_key: str, model: str = "grok-4.5", base_url: str = "") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def write(self, *, goal: str, element: Element, observation: Observation) -> str:
        from core_ai import GrokProvider, Message, ModelRegistry

        registry = ModelRegistry()
        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        registry.register("grok", GrokProvider(**kwargs))
        prompt = (
            "Write the exact string that should be typed into the field. "
            'Reply with JSON {"text": "..."} and nothing else.\n'
            f"Goal: {goal}\n"
            f"Field: {element.label()}\n"
            f"Page title: {observation.title}\n"
            f"Page text: {observation.text[:800]}"
        )
        chunks: list[str] = []
        async for event in registry.stream(
            f"grok:{self.model}",
            [Message(role="user", content=prompt)],
            max_output_tokens=80,
        ):
            if event.type == "text_delta" and event.delta:
                chunks.append(event.delta)
        text = _parse_text("".join(chunks))
        if not text:
            raise TextUnavailable("text model returned an empty string")
        return text


def build_text_writer(explicit: str = "") -> Optional[TextWriter]:
    model = (explicit or os.environ.get("SYMPHONY_BROWSER_TEXT_MODEL") or "").strip()
    key = (os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or "").strip()
    if model.startswith("grok:") or (not model and key):
        name = model.split(":", 1)[1] if model.startswith("grok:") else (
            os.environ.get("GROK_MODEL") or os.environ.get("XAI_MODEL") or "grok-4.5"
        )
        if not key:
            return None
        return GrokTextWriter(api_key=key, model=name)
    if not model:
        return None
    return None


_SECRET = re.compile(r"password|passcode|secret|otp", re.IGNORECASE)


def redact_typed(element: Optional[Element], text: str) -> str:
    if element is not None and _SECRET.search(element.name):
        return "***" if text else ""
    return text


__all__ = [
    "GrokTextWriter",
    "StaticTextWriter",
    "TextUnavailable",
    "TextWriter",
    "build_text_writer",
    "redact_typed",
]
