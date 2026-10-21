"""JSONL frames and the event sink that writes them."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from core_ai.content import image_part_from_bytes, sniff_image_media_type
from core_ai.types import Content
from core_harness import EventSink, HumanInteraction

from coding_agent.widget_fields import EventFields


def _write(frame: Mapping[str, Any]) -> None:
    """Write through the package so ``stdio.write_frame`` stays patchable."""
    from coding_agent.protocols import stdio

    stdio.write_frame(frame)

PROTOCOL_VERSION = 4
CAPABILITIES = [
    "runs", "resume", "interrupt", "input", "steer", "models", "images", "subagents", "commands",
    "sessions", "model_switch", "widget_fields", "artifacts",
]
# Approval fields lifted from the question's metadata onto input_requested.
APPROVAL_FIELDS = ("target", "detail", "bytes")


def write_frame(frame: Mapping[str, Any]) -> None:
    sys.__stdout__.write(json.dumps(frame, default=str, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


def user_content(prompt: str, attachments: Sequence[str]) -> Content:
    """Inline staged image bytes using the same canonical parts as the TUI."""
    if not attachments:
        return prompt
    if len(attachments) > 8:
        raise ValueError("at most eight images can be attached")
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for raw in attachments:
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("attachment must be a regular image under 20 MiB")
        payload = path.read_bytes()
        media = sniff_image_media_type(payload, filename=path.name)
        if media is None:
            raise ValueError(f"unsupported image: {path.name}")
        parts.append(image_part_from_bytes(payload, media_type=media, filename=path.name))
    return parts


class StdioSink(EventSink):
    """Write each event as a frame.

    A question is the ``question_asked`` event like in every other host.
    Protocol 2 hosts read ``input_requested``, so that frame follows it.
    Protocol 3 adds the widget fields from :class:`EventFields`, and an
    approval's ``target``, ``detail`` and ``bytes`` on ``input_requested`` itself.
    """

    def __init__(self) -> None:
        super().__init__()
        self.interaction = HumanInteraction(self)
        self.fields = EventFields()

    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        for name, body in self.fields.apply(event_type, payload):
            _write({"type": "event", "event": name, "payload": body})
            if name != "question_asked":
                continue
            known = {"request_id", "question", "choices", "default", "kind"}
            frame: Dict[str, Any] = {
                "type": "input_requested",
                **{key: body.get(key) for key in ("request_id", "question", "choices", "default", "kind")},
                "metadata": {key: value for key, value in body.items() if key not in known},
            }
            if body.get("kind") == "approval":
                frame.update({key: body.get(key) for key in APPROVAL_FIELDS})
            _write(frame)


__all__ = ["APPROVAL_FIELDS", "CAPABILITIES", "PROTOCOL_VERSION", "StdioSink", "user_content", "write_frame"]
