"""Free text is the only step that is not a Jev choice.

If the goal already contains the string (a quote, or "search for …"), Jev
picks it as ``type_value`` and this module is not called. Otherwise a small
chat model writes one string. Grok is the only writer; it is on when
``XAI_API_KEY`` is set.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Protocol

from core_ai import GrokProvider, Message, ModelRegistry
from core_ai.providers.catalog import get_provider, provider_api_key

from browser_agent.models import Element, Observation


class TextUnavailable(RuntimeError):
    """The writer produced no usable string; the step becomes BLOCKED."""


class TextWriter(Protocol):
    """Writes the one string to type into ``element``."""

    async def write(self, *, goal: str, element: Element, observation: Observation) -> str: ...


def _parse_text(raw: str) -> str:
    """The ``text`` of a JSON reply, else the first line; "" for an empty reply."""
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return payload["text"].strip()
    lines = stripped.splitlines()
    return lines[0].strip().strip('"')[:200] if lines else ""


class GrokTextWriter:
    """One short Grok completion. Not used to choose the element or the operation."""

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self.registry = ModelRegistry()
        self.registry.register("grok", GrokProvider(api_key=api_key, base_url=base_url))
        self.model = model

    async def write(self, *, goal: str, element: Element, observation: Observation) -> str:
        """Ask Grok for the string. Raises TextUnavailable when it returns nothing."""
        prompt = (
            "Write the exact string that should be typed into the field. "
            'Reply with JSON {"text": "..."} and nothing else.\n'
            f"Goal: {goal}\n"
            f"Field: {element.label()}\n"
            f"Page title: {observation.title}\n"
            f"Page text: {observation.text[:800]}"
        )
        chunks: list[str] = []
        async for event in self.registry.stream(
            self.model, [Message(role="user", content=prompt)], max_output_tokens=80
        ):
            if event.type == "text_delta" and event.delta:
                chunks.append(event.delta)
        text = _parse_text("".join(chunks))
        if not text:
            raise TextUnavailable("text model returned an empty string")
        return text


def build_text_writer(explicit: str = "") -> Optional[TextWriter]:
    """Grok for ``grok:<model>`` or no model; None without ``XAI_API_KEY``.

    Any other ``--text-model`` / ``SYMPHONY_BROWSER_TEXT_MODEL`` raises ValueError.
    """
    spec = get_provider("grok")
    model = (explicit or os.getenv("SYMPHONY_BROWSER_TEXT_MODEL", "")).strip() or spec.default_model
    if not model.startswith("grok:"):
        raise ValueError(f"The browser text model must be grok:<model>, got {model!r}.")
    api_key = provider_api_key(spec)
    if not api_key:
        return None
    base_url = os.getenv(spec.base_url_env, "").strip() or spec.default_base_url
    return GrokTextWriter(api_key=api_key, model=model, base_url=base_url)


__all__ = ["GrokTextWriter", "TextUnavailable", "TextWriter", "build_text_writer"]
