"""JSONL frames and the event sink that writes them."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from core_ai.content import image_part_from_bytes, sniff_image_media_type
from core_ai.types import Content
from core_harness import EventSink, HumanInteraction


def _write(frame: Mapping[str, Any]) -> None:
    """Write through the package so ``stdio.write_frame`` stays patchable."""
    from coding_agent.protocols import stdio

    stdio.write_frame(frame)

PROTOCOL_VERSION = 2
CAPABILITIES = ["runs", "resume", "interrupt", "input", "steer", "models", "images", "subagents", "commands", "sessions", "model_switch"]


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
    """

    def __init__(self) -> None:
        super().__init__()
        self.interaction = HumanInteraction(self)

    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        _write({"type": "event", "event": event_type, "payload": payload})
        if event_type == "question_asked":
            known = {"request_id", "question", "choices", "default", "kind"}
            _write({
                "type": "input_requested",
                **{key: payload.get(key) for key in ("request_id", "question", "choices", "default", "kind")},
                "metadata": {key: value for key, value in payload.items() if key not in known},
            })


__all__ = ["CAPABILITIES", "PROTOCOL_VERSION", "StdioSink", "user_content", "write_frame"]
