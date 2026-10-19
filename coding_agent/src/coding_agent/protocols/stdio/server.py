"""One-turn stdio command loop."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Mapping

from core_harness import Answer, Interrupt, UserInput

from coding_agent.commands.catalog import EFFORTS
from coding_agent.config import ensure_spawn_settings
from coding_agent.protocols.stdio import commands as command_module
from coding_agent.protocols.stdio.commands import load_state
from coding_agent.protocols.stdio.requests import ready_frame, select_model, session_history, session_list
from coding_agent.protocols.stdio.transport import PROTOCOL_VERSION, StdioSink

if TYPE_CHECKING:
    from coding_agent.agent import CodingAgent

CLIENTS = ("zeron", "web")

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
            if effort not in EFFORTS:
                raise ValueError(f"Unsupported reasoning effort: {effort}")
            agent.harness.reasoning_effort = None if effort == "default" else effort
        stripped = prompt.lstrip()
        parts = stripped[1:].split(None, 1) if stripped.startswith("/") else []
        name = parts[0].lower() if parts else ""
        stdio = _package()
        names = {item["name"] for item in command_module.catalog(extra=agent.user_addons.surface.slash_commands)}
        if name in names:
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
    client: str = "zeron",
) -> int:
    stdio = _package()
    stdio.load_provider_env(workspace)
    sink = StdioSink()
    try:
        agent: CodingAgent = stdio.build_agent(
            workspace=workspace,
            model_id=model,
            session_id=session_id,
            sink=sink,
            config=ensure_spawn_settings(workspace, overrides={"unattended": True}) if unattended else None,
            client=client,
        )
        load_state(agent)
    except Exception as exc:
        _package().write_frame({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    stdio.write_frame(ready_frame(agent, workspace, client))
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
                    "commands": command_module.catalog(workspace, agent.user_addons.surface.slash_commands),
                    "protocol_version": PROTOCOL_VERSION,
                })
            except Exception as exc:
                stdio.write_frame({
                    "type": "error", "request_id": request_id, "message": f"{type(exc).__name__}: {exc}",
                })
        elif kind in {"session/list", "session/history", "model"}:
            request_id = _request_id(command, kind)
            if request_id is None:
                continue
            try:
                if kind == "session/list":
                    stdio.write_frame(await session_list(agent, request_id))
                elif kind == "session/history":
                    target = command.get("session_id")
                    if not isinstance(target, str) or not target:
                        raise ValueError("session/history requires session_id")
                    stdio.write_frame(await session_history(agent, request_id, target))
                else:
                    selected = command.get("model")
                    if not isinstance(selected, str) or not selected:
                        raise ValueError("model requires a model id")
                    if run is not None and not run.done():
                        raise RuntimeError("model cannot change during an active run")
                    stdio.write_frame(select_model(agent, request_id, selected))
            except Exception as exc:
                stdio.write_frame({
                    "type": "error", "request_id": request_id, "message": f"{type(exc).__name__}: {exc}",
                })
        elif kind == "answer":
            answer_id = str(command.get("request_id") or "")
            if not agent.harness.submit(Answer(answer_id, str(command.get("value", "")))):
                stdio.write_frame({
                    "type": "error", "request_id": answer_id, "message": "answer rejected: no question is waiting on that id",
                })
        elif kind == "interrupt":
            # A slash command runs outside the harness; cancel its task instead.
            if run is not None and not run.done() and not agent.harness.submit(Interrupt()):
                run.cancel()
        elif kind == "steer":
            prompt = command.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                stdio.write_frame({"type": "error", "message": "prompt is required"})
            elif not agent.harness.submit(UserInput(prompt)):
                stdio.write_frame({"type": "error", "message": "steer requires an active run"})
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
        elif kind == "run":
            stdio.write_frame({"type": "error", "message": "run rejected: a run is already active"})
        else:
            stdio.write_frame({"type": "error", "message": f"invalid command: {kind}"})


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="symphony stdio")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--session-id")
    parser.add_argument("--unattended", action="store_true", help="Auto-approve tools subject to Symphony deny rules")
    parser.add_argument("--client", choices=CLIENTS, default="zeron", help="Host product that owns the sessions")
    args = parser.parse_args(argv)
    # Libraries may print diagnostics; stdout belongs exclusively to JSONL.
    sys.stdout = sys.stderr
    return asyncio.run(serve(
        Path(args.workspace).expanduser().resolve(),
        args.model,
        args.session_id,
        unattended=args.unattended,
        client=args.client,
    ))


__all__ = ["main", "serve"]
