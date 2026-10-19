"""Widget fields every host adds to harness events (protocol 3).

The harness emits tool, approval and subagent events. Hosts (the stdio
protocol and the TUI) pass each one through :class:`EventFields`, which adds
fields derived from data Symphony already owns, keeping every existing key:

- ``tool_execution_started``: ``call_id``, ``parent_call_id``
- ``tool_execution_output``: ``call_id``, ``stream``, ``parent_call_id``
- ``tool_execution_completed``: ``call_id``, ``exit_code``, ``summary``, ``parent_call_id``
- ``agent_spawned``: ``parent_call_id`` (the spawning call)
- a child's ``turn_started`` is followed by one ``subagent_step`` event

``parent_call_id`` is the ``tool_call_id`` of the ``spawn_agent`` call that
started the emitting child (from ``agent_spawned.tool_call_id``); top-level
events carry ``null``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from coding_agent.tools.bash import BashTool
from coding_agent.tools.summary import summarize

if TYPE_CHECKING:
    from coding_agent.agent import CodingAgent

Payload = dict[str, object]

SUBAGENT_STEP = "subagent_step"


def _str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


class EventFields:
    """Per-session state for the derived fields.

    Share one instance across forked sinks. The session store keeps its own
    instance so the journal holds the same fields (see ``build_agent``).
    """

    def __init__(self) -> None:
        # Bound to the session's BashTool.exit_codes by ``bind``. Read, never
        # popped: the session store and the host sink both read each code.
        self.exit_codes: dict[str, int] = {}
        self._arguments: dict[str, Mapping[str, object]] = {}
        # child agent id -> (spawning call id, parent session id)
        self._spawns: dict[str, tuple[str, str]] = {}
        # tool call id -> parent_call_id, for output chunks, which carry no agent ids.
        self._call_parents: dict[str, str | None] = {}

    def bind(self, agent: CodingAgent) -> None:
        """Read exit codes from the agent's own bash tool."""
        for tool in agent.tools:
            if isinstance(tool, BashTool):
                self.exit_codes = tool.exit_codes

    def apply(self, event_type: str, payload: Mapping[str, object]) -> list[tuple[str, Payload]]:
        """The event with its added fields, then any derived events, in emit order."""
        out: Payload = dict(payload)
        agent_id = _str(payload, "agent_id")
        spawn = self._spawns.get(agent_id) if _str(payload, "parent_id") else None
        parent_call_id = spawn[0] if spawn is not None else None
        call_id = _str(payload, "tool_call_id")
        if event_type == "agent_spawned":
            child_id = _str(payload, "child_id")
            if child_id and call_id:
                self._spawns[child_id] = (call_id, _str(payload, "session_id"))
            out["parent_call_id"] = call_id or None
            return [(event_type, out)]
        if event_type == "tool_execution_started":
            arguments = payload.get("arguments")
            if isinstance(arguments, Mapping):
                self._arguments[call_id] = arguments
            self._call_parents[call_id] = parent_call_id
            out["call_id"] = call_id
        elif event_type == "tool_execution_output":
            out["call_id"] = call_id
            out.setdefault("stream", "stdout")
            out["parent_call_id"] = self._call_parents.get(call_id)
            return [(event_type, out)]
        elif event_type == "tool_execution_completed":
            out["call_id"] = call_id
            out["exit_code"] = self.exit_codes.get(call_id)
            out["summary"] = summarize(
                _str(payload, "tool_name"),
                self._arguments.pop(call_id, {}),
                _str(payload, "result"),
                failed=payload.get("status") != "success",
            )
            self._call_parents.pop(call_id, None)
        elif event_type == "turn_started" and spawn is not None:
            out["parent_call_id"] = parent_call_id
            step: Payload = {
                "session_id": spawn[1],
                "agent_id": agent_id,
                "parent_id": _str(payload, "parent_id"),
                "parent_call_id": parent_call_id,
                "turn": payload.get("turn"),
                "started_at": payload.get("started_at", payload.get("ts")),
            }
            return [(event_type, out), (SUBAGENT_STEP, step)]
        else:
            return [(event_type, out)]
        out["parent_call_id"] = parent_call_id
        return [(event_type, out)]


__all__ = ["SUBAGENT_STEP", "EventFields"]
