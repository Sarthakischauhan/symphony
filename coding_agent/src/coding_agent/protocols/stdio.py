"""Interactive, line-delimited JSON transport for external agent managers.

Only protocol frames go to stdout. Each process handles one turn; subsequent
turns resume the persisted Symphony session by its id.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from core_ai.content import image_part_from_bytes, sniff_image_media_type
from core_harness import EventSink
from core_harness.events import normalize_event_type
from core_harness.models import ControlPlaneEventType

from coding_agent.agent import build_agent
from coding_agent.config import ensure_spawn_settings
from coding_agent.credentials import load_provider_env

PROTOCOL_VERSION = 1
CAPABILITIES = ["runs", "resume", "interrupt", "input", "models", "images"]


def write_frame(frame: dict[str, Any]) -> None:
    sys.__stdout__.write(json.dumps(frame, default=str, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


def user_content(prompt: str, attachments: Sequence[str]) -> str | list[dict[str, Any]]:
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
        write_frame({"type": "event", "event": normalize_event_type(event_type), "payload": payload or {}})

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
        write_frame({
            "type": "input_requested", "request_id": request_id,
            "question": question, "choices": list(choices), "default": default,
            "kind": kind, "metadata": metadata or {},
        })
        try:
            return await answer
        finally:
            self.pending.pop(request_id, None)


async def serve(workspace: Path, model: str | None, session_id: str | None, *, unattended: bool = False) -> int:
    load_provider_env(workspace)
    sink = StdioSink()
    try:
        agent = build_agent(
            workspace=workspace, model_id=model, session_id=session_id, sink=sink,
            config=ensure_spawn_settings(workspace, overrides={"unattended": True}) if unattended else None,
        )
    except Exception as exc:
        write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    write_frame({
        "type": "ready", "session_id": agent.session_id,
        "model": getattr(agent.harness, "model_id", model or ""),
        "protocol_version": PROTOCOL_VERSION, "capabilities": CAPABILITIES,
    })
    run: asyncio.Task[Any] | None = None
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            if run is not None and not run.done():
                run.cancel()
                await asyncio.gather(run, return_exceptions=True)
            return 0
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            write_frame({"type": "error", "message": "invalid JSON command"})
            continue
        kind = command.get("type")
        if kind == "answer":
            pending = sink.pending.get(command.get("request_id"))
            if pending and not pending.done():
                pending.set_result(str(command.get("value", "")))
        elif kind == "interrupt":
            if run is not None and not run.done():
                run.cancel()
        elif kind == "run" and (run is None or run.done()):
            prompt = command.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                write_frame({"type": "error", "message": "prompt is required"})
                continue

            async def execute(task: str, attachments: Sequence[str]) -> None:
                try:
                    await agent.run(user_content(task, attachments))
                    write_frame({"type": "done", "status": "completed"})
                except asyncio.CancelledError:
                    write_frame({"type": "done", "status": "interrupted"})
                except Exception as exc:
                    write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                    write_frame({"type": "done", "status": "errored"})

            paths = command.get("attachments") or []
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                write_frame({"type": "error", "message": "attachments must be a list of paths"})
                continue
            run = asyncio.create_task(execute(prompt, paths))
        else:
            write_frame({"type": "error", "message": f"invalid command: {kind}"})


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="symphony stdio")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--session-id")
    parser.add_argument("--models", action="store_true", help="List models available to this Symphony installation")
    parser.add_argument("--unattended", action="store_true", help="Auto-approve tools subject to Symphony deny rules")
    args = parser.parse_args(argv)
    # Libraries may print diagnostics; stdout belongs exclusively to JSONL.
    sys.stdout = sys.stderr
    if args.models:
        from core_ai import build_default_registry, default_model_id

        load_provider_env(Path(args.workspace).expanduser().resolve())
        try:
            registry = build_default_registry()
            models = [
                {
                    "id": info.full_id,
                    "label": info.id,
                    "description": info.provider,
                    "reasoning_levels": [level for level, _ in info.thinking_level_map if level != "off"],
                }
                for info in registry.models()
                if info.provider in registry.namespaces()
            ]
            default = default_model_id(registry)
            selected = next((item for item in models if item["id"] == default), None)
            if selected is None:
                selected = {"id": default, "label": default.split(":", 1)[-1], "description": "Symphony default", "reasoning_levels": []}
            models = [selected, *[item for item in models if item["id"] != default]]
            write_frame({"type": "models", "models": models, "default": default,
                         "protocol_version": PROTOCOL_VERSION})
        except Exception as exc:
            write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            return 1
        return 0
    return asyncio.run(serve(
        Path(args.workspace).expanduser().resolve(), args.model, args.session_id,
        unattended=args.unattended,
    ))


__all__ = ["StdioSink", "main", "serve"]
