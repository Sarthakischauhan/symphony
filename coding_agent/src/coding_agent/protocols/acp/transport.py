"""JSON-RPC 2.0 over stdio, one message per line."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, Mapping

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def write_message(message: Mapping[str, Any]) -> None:
    sys.__stdout__.write(json.dumps(message, default=str, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


def _write(message: Mapping[str, Any]) -> None:
    """Write through the package so ``acp.write_message`` stays patchable."""
    from coding_agent.protocols import acp

    acp.write_message(message)


class Connection:
    """Outbound half of the connection, and the replies to our own requests."""

    def __init__(self) -> None:
        self._next_id = 0
        self._waiting: Dict[int, asyncio.Future[Any]] = {}

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        _write({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, request_id: Any, result: Mapping[str, Any]) -> None:
        _write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def fail(self, request_id: Any, code: int, message: str) -> None:
        _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    async def request(self, method: str, params: Mapping[str, Any]) -> Any:
        """Ask the client and wait for its result. ``None`` if it errored."""
        self._next_id += 1
        request_id = self._next_id
        reply = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = reply
        _write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await reply
        finally:
            self._waiting.pop(request_id, None)

    def resolve(self, message: Mapping[str, Any]) -> None:
        """Deliver the client's reply to one of our requests."""
        reply = self._waiting.get(message.get("id"))  # type: ignore[arg-type]
        if reply is not None and not reply.done():
            reply.set_result(message.get("result"))


__all__ = [
    "Connection",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "write_message",
]
