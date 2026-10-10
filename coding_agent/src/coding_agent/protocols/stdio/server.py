"""One-turn stdio command loop."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Mapping

from coding_agent.config import ensure_spawn_settings
from coding_agent.protocols.stdio import commands as command_module
from coding_agent.protocols.stdio.commands import load_state
from coding_agent.protocols.stdio.transport import CAPABILITIES, PROTOCOL_VERSION, StdioSink

# Look these up on the package so tests can patch ``stdio.write_frame`` and
# ``stdio.build_agent`` without reaching into the implementation modules.
def _package() -> Any:
    from coding_agent.protocols import stdio

    return stdio


def _request_id(command: Mapping[str, Any], kind: str) -> str | None:
    request_id = command.get("request_id")
    if isinstance(request_id, str) and request_id:
        return request_id
    _package().write_frame({"type": "error", "message": f"{kind} requires request_id"})
    return None


async def _run_turn(agent: Any, prompt: str, attachments: Sequence[str], effort: str | None) -> None:
    try:
        if effort is not None:
            from coding_agent.tui.commands.catalog import EFFORTS

            if effort not in EFFORTS:
                raise ValueError(f"Unsupported reasoning effort: {effort}")
            agent.harness.reasoning_effort = None if effort == "default" else effort
        stripped = prompt.lstrip()
        parts = stripped[1:].split(None, 1) if stripped.startswith("/") else []
        name = parts[0].lower() if parts else ""
        stdio = _package()
        if name in {item["name"] for item in command_module.catalog()}:
            if attachments:
                raise ValueError("Slash commands do not accept image attachments")
            result = await command_module.execute(agent, stripped)
            stdio.write_frame({"type": "event", "event": "text_delta", "payload": {"delta": result}})
        else:
            await agent.run(stdio.user_content(prompt, attachments))
        stdio.write_frame({"type": "done", "status": "completed"})
    except asyncio.CancelledError:
        _package().write_frame({"type": "done", "status": "interrupted"})
    except Exception as exc:
        stdio = _package()
        stdio.write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        stdio.write_frame({"type": "done", "status": "errored"})


async def serve(
    workspace: Path,
    model: str | None,
    session_id: str | None,
    *,
    unattended: bool = False,
) -> int:
    stdio = _package()
    stdio.load_provider_env(workspace)
    sink = StdioSink()
    try:
        agent = stdio.build_agent(
            workspace=workspace,
            model_id=model,
            session_id=session_id,
            sink=sink,
            config=ensure_spawn_settings(workspace, overrides={"unattended": True}) if unattended else None,
        )
        load_state(agent)
        persistence = getattr(agent, "persistence", None)
        if persistence is not None:
            # Zeron talks to Symphony over stdio. Its chats must not appear
            # in the TUI resume picker.
            persistence.client = "zeron"
    except Exception as exc:
        _package().write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    stdio.write_frame({
        "type": "ready",
        "session_id": agent.session_id,
        "model": getattr(agent.harness, "model_id", model or ""),
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": CAPABILITIES,
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
            stdio.write_frame({"type": "error", "message": "invalid JSON command"})
            continue
        if not isinstance(command, dict):
            stdio.write_frame({"type": "error", "message": "invalid command: not an object"})
            continue
        kind = command.get("type")
        if kind == "model/list":
            request_id = _request_id(command, kind)
            if request_id is None:
                continue
            try:
                stdio.write_frame(stdio.model_catalog(agent.registry, request_id))
            except Exception as exc:
                stdio.write_frame({
                    "type": "error", "request_id": request_id, "message": f"{type(exc).__name__}: {exc}",
                })
        elif kind == "command/list":
            request_id = _request_id(command, kind)
            if request_id is None:
                continue
            try:
                stdio.write_frame({
                    "type": "commands",
                    "request_id": request_id,
                    "commands": command_module.catalog(workspace),
                    "protocol_version": PROTOCOL_VERSION,
                })
            except Exception as exc:
                stdio.write_frame({
                    "type": "error", "request_id": request_id, "message": f"{type(exc).__name__}: {exc}",
                })
        elif kind == "answer":
            pending = sink.pending.get(command.get("request_id"))
            if pending and not pending.done():
                pending.set_result(str(command.get("value", "")))
        elif kind == "interrupt":
            if run is not None and not run.done():
                run.cancel()
        elif kind == "run" and (run is None or run.done()):
            prompt = command.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                stdio.write_frame({"type": "error", "message": "prompt is required"})
                continue
            paths = command.get("attachments") or []
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                stdio.write_frame({"type": "error", "message": "attachments must be a list of paths"})
                continue
            effort = command.get("reasoning_effort")
            run = asyncio.create_task(_run_turn(agent, prompt, paths, effort if isinstance(effort, str) else None))
        else:
            stdio.write_frame({"type": "error", "message": f"invalid command: {kind}"})


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="symphony stdio")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--session-id")
    parser.add_argument("--unattended", action="store_true", help="Auto-approve tools subject to Symphony deny rules")
    args = parser.parse_args(argv)
    # Libraries may print diagnostics; stdout belongs exclusively to JSONL.
    sys.stdout = sys.stderr
    return asyncio.run(serve(
        Path(args.workspace).expanduser().resolve(),
        args.model,
        args.session_id,
        unattended=args.unattended,
    ))


__all__ = ["main", "serve"]
