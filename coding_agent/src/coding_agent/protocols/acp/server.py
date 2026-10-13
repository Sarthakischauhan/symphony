"""Agent Client Protocol host: one stdio process, any number of sessions.

A thin translator. Events become ``session/update`` notifications, a
question becomes a ``session/request_permission`` request, and the client's
prompt, cancel, and permission reply become ``CoreHarness.submit`` ops.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Dict, Mapping

from core_harness import (
    Answer,
    EventSink,
    HarnessCancelled,
    HarnessLimitExceeded,
    HumanInteraction,
    Interrupt,
    UserInput,
)

from coding_agent.config import ensure_spawn_settings
from coding_agent.protocols.acp.mapping import (
    PROTOCOL_VERSION,
    permission_answer,
    permission_request,
    prompt_text,
    session_updates,
    stop_reason_for_limit,
)
from coding_agent.protocols.acp.transport import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    Connection,
)


def _package() -> Any:
    """Look names up on the package so tests can patch ``acp.build_agent``."""
    from coding_agent.protocols import acp

    return acp


class AcpSink(EventSink):
    """Send each event to the client in ACP terms."""

    def __init__(self, connection: Connection) -> None:
        super().__init__()
        self.interaction = HumanInteraction(self)
        self.connection = connection
        self.session_id = ""
        self.submit: Any = None
        self._asking: set[asyncio.Task[None]] = set()

    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        if event_type == "question_asked":
            task = asyncio.create_task(self._ask(payload))
            self._asking.add(task)
            task.add_done_callback(self._asking.discard)
            return
        for update in session_updates(event_type, payload):
            self.connection.notify("session/update", {"sessionId": self.session_id, "update": update})

    async def _ask(self, payload: Mapping[str, Any]) -> None:
        """Put one question to the client and send its answer back as an op."""
        outcome: Any = None
        # ACP permission requests carry options. A free-text question has
        # none to offer, so it takes its default.
        if payload.get("choices"):
            reply = await self.connection.request(
                "session/request_permission", permission_request(self.session_id, payload)
            )
            outcome = reply.get("outcome") if isinstance(reply, Mapping) else None
        if callable(self.submit):
            self.submit(Answer(str(payload.get("request_id") or ""), permission_answer(outcome, payload)))


class Session:
    def __init__(self, agent: Any, sink: AcpSink) -> None:
        self.agent = agent
        self.sink = sink
        self.run: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self.run is not None and not self.run.done()


class Server:
    def __init__(self, *, model: str | None = None, unattended: bool = False) -> None:
        self.connection = Connection()
        self.sessions: Dict[str, Session] = {}
        self.model = model
        self.unattended = unattended

    async def handle(self, message: Mapping[str, Any]) -> None:
        """Dispatch one message from the client."""
        method = message.get("method")
        if method is None:
            self.connection.resolve(message)
            return
        request_id = message.get("id")
        params = message.get("params")
        params = params if isinstance(params, Mapping) else {}
        handler = {
            "initialize": self._initialize,
            "session/new": self._new_session,
            "session/prompt": self._prompt,
            "session/cancel": self._cancel,
            "_symphony/steer": self._steer,
        }.get(str(method))
        if handler is None:
            if request_id is not None:
                self.connection.fail(request_id, METHOD_NOT_FOUND, f"method not found: {method}")
            return
        try:
            result = await handler(params, request_id)
        except ValueError as exc:
            if request_id is not None:
                self.connection.fail(request_id, INVALID_PARAMS, str(exc))
            return
        except Exception as exc:
            if request_id is not None:
                self.connection.fail(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
            return
        if result is not None and request_id is not None:
            self.connection.respond(request_id, result)

    async def _initialize(self, params: Mapping[str, Any], request_id: Any) -> Dict[str, Any]:
        del params, request_id
        try:
            release = version("symphony-code")
        except PackageNotFoundError:
            release = "unknown"
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {"image": False, "audio": False, "embeddedContext": True},
                "_meta": {"symphony": {"steer": True}},
            },
            "agentInfo": {"name": "symphony", "title": "Symphony", "version": release},
            "authMethods": [],
        }

    async def _new_session(self, params: Mapping[str, Any], request_id: Any) -> Dict[str, Any]:
        del request_id
        cwd = params.get("cwd")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise ValueError("cwd must be an absolute path")
        workspace = Path(cwd)
        acp = _package()
        acp.load_provider_env(workspace)
        sink = AcpSink(self.connection)
        agent = acp.build_agent(
            workspace=workspace,
            model_id=self.model,
            sink=sink,
            config=ensure_spawn_settings(workspace, overrides={"unattended": True}) if self.unattended else None,
            client="acp",
        )
        sink.session_id = str(agent.session_id)
        sink.submit = agent.harness.submit
        self.sessions[sink.session_id] = Session(agent, sink)
        return {"sessionId": sink.session_id}

    def _session(self, params: Mapping[str, Any]) -> Session:
        session = self.sessions.get(str(params.get("sessionId") or ""))
        if session is None:
            raise ValueError("unknown sessionId")
        return session

    async def _prompt(self, params: Mapping[str, Any], request_id: Any) -> None:
        session = self._session(params)
        blocks = params.get("prompt")
        text = prompt_text(blocks) if isinstance(blocks, list) else ""
        if not text.strip():
            raise ValueError("prompt has no text")
        if session.busy:
            self.connection.fail(request_id, INVALID_REQUEST, "a prompt is already running in this session")
            return None
        session.run = asyncio.create_task(self._run(session, text, request_id))
        return None

    async def _run(self, session: Session, text: str, request_id: Any) -> None:
        """Run one prompt turn and answer the request with its stop reason."""
        try:
            await session.agent.run(text)
            stop = "end_turn"
        except (HarnessCancelled, asyncio.CancelledError):
            stop = "cancelled"
        except HarnessLimitExceeded as exc:
            stop = stop_reason_for_limit(exc)
        except Exception as exc:
            self.connection.fail(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
            return
        self.connection.respond(request_id, {"stopReason": stop})

    async def _cancel(self, params: Mapping[str, Any], request_id: Any) -> None:
        del request_id
        self._session(params).agent.harness.submit(Interrupt("user_cancel"))
        return None

    async def _steer(self, params: Mapping[str, Any], request_id: Any) -> Dict[str, Any]:
        del request_id
        blocks = params.get("prompt")
        text = prompt_text(blocks) if isinstance(blocks, list) else ""
        if not text.strip():
            raise ValueError("prompt has no text")
        return {"accepted": bool(self._session(params).agent.harness.submit(UserInput(text)))}

    async def shutdown(self) -> None:
        runs = [session.run for session in self.sessions.values() if session.busy]
        for run in runs:
            run.cancel()
        await asyncio.gather(*runs, return_exceptions=True)


async def serve(*, model: str | None = None, unattended: bool = False) -> int:
    server = Server(model=model, unattended=unattended)
    acp = _package()
    while True:
        line = await asyncio.to_thread(acp.sys.stdin.readline)
        if not line:
            await server.shutdown()
            return 0
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            server.connection.fail(None, PARSE_ERROR, "invalid JSON")
            continue
        if not isinstance(message, dict):
            server.connection.fail(None, INVALID_REQUEST, "message must be an object")
            continue
        await server.handle(message)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="symphony acp")
    parser.add_argument("--model")
    parser.add_argument("--unattended", action="store_true", help="Auto-approve tools subject to Symphony deny rules")
    args = parser.parse_args(argv)
    # Libraries may print diagnostics; stdout belongs exclusively to JSON-RPC.
    sys.stdout = sys.stderr
    return asyncio.run(serve(model=args.model, unattended=args.unattended))


__all__ = ["AcpSink", "Server", "main", "serve"]
