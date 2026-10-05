"""JSONL frames and the event sink that writes them."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from core_ai.content import image_part_from_bytes, sniff_image_media_type
from core_ai.types import Content
from core_harness import EventSink
from core_harness.events import normalize_event_type
from core_harness.models import ControlPlaneEventType


def _write(frame: Mapping[str, Any]) -> None:
    """Write through the package so ``stdio.write_frame`` stays patchable."""
    from coding_agent.protocols import stdio

    stdio.write_frame(frame)

PROTOCOL_VERSION = 2
CAPABILITIES = ["runs", "resume", "interrupt", "input", "models", "images", "subagents", "commands"]


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
    def __init__(self) -> None:
        super().__init__()
        self.pending: dict[str, asyncio.Future[str]] = {}

    async def emit(
        self,
        event_type: str | ControlPlaneEventType,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        _write({"type": "event", "event": normalize_event_type(event_type), "payload": payload or {}})

    async def request_user_input(
        self,
        *,
        question: str,
        choices: Sequence[str] = (),
        default: str = "",
        kind: str = "question",
        metadata: Optional[Dict[str, Any]] = None,
        emit: Any = None,
    ) -> str:
        del emit
        request_id = str(uuid.uuid4())
        answer = asyncio.get_running_loop().create_future()
        self.pending[request_id] = answer
        _write({
            "type": "input_requested", "request_id": request_id,
            "question": question, "choices": list(choices), "default": default,
            "kind": kind, "metadata": metadata or {},
        })
        try:
            return await answer
        finally:
            self.pending.pop(request_id, None)


__all__ = ["CAPABILITIES", "PROTOCOL_VERSION", "StdioSink", "user_content", "write_frame"]
