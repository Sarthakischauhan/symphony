"""Child-agent event ingest: record state from parent-sink child events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from coding_agent.tui.transcript.messages import compact_json, preview_text


@dataclass
class SubagentRecord:
    """Live child-agent transcript, keyed by ``agent_id``."""

    agent_id: str
    parent_id: str
    label: str
    prompt: str
    status: str = "running"
    model_id: str = ""
    output_text: str = ""
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    tool_call_id: str = ""
    run_id: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    _seen_events: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _widgets: list[Any] = field(default_factory=list, repr=False)

    def _tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        call_id = str(payload.get("tool_call_id") or f"tool-{len(self.tools)}")
        existing = next(
            (tool for tool in self.tools if tool.get("id") == call_id),
            None,
        )
        if existing is not None:
            return existing
        tool = {
            "id": call_id,
            "name": str(payload.get("tool_name") or "tool"),
            "status": "preparing",
            "arguments": {},
            "raw_arguments": "",
            "summary": "",
            "result": "",
        }
        self.tools.append(tool)
        return tool

    def ingest(self, event_type: str, payload: dict[str, Any]) -> None:
        if payload.get("parent_id") and (
            payload.get("agent_id") != self.agent_id
            or payload.get("parent_id") != self.parent_id
        ):
            return
        if payload.get("run_id") and isinstance(payload.get("seq"), int):
            key = (str(payload["run_id"]), payload["seq"])
            if key in self._seen_events:
                return
            self._seen_events.add(key)
        self.events.append((event_type, dict(payload)))
        if event_type == "run_started":
            self.run_id = str(payload.get("run_id") or self.run_id)
            self.session_id = str(payload.get("session_id") or self.session_id)
            self.status = "running"
            self.output_text = ""
            self.model_id = str(payload.get("model_id") or self.model_id)
        elif event_type == "tool_call_started":
            tool = self._tool(payload)
            tool["name"] = str(payload.get("tool_name") or tool["name"])
        elif event_type == "tool_call_delta":
            tool = self._tool(payload)
            raw = str(tool.get("raw_arguments") or "") + str(payload.get("delta") or "")
            tool["raw_arguments"] = raw
            tool["summary"] = raw
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = None
            if isinstance(arguments, dict):
                tool["arguments"] = arguments
                tool["summary"] = compact_json(arguments)
        elif event_type == "tool_execution_started":
            tool = self._tool(payload)
            arguments = payload.get("arguments") or {}
            tool.update(
                name=str(payload.get("tool_name") or tool["name"]),
                status="running",
                arguments=arguments,
                summary=compact_json(arguments) if arguments else tool["summary"],
            )
        elif event_type == "tool_execution_completed":
            tool = self._tool(payload)
            result = payload.get("result") or ""
            tool.update(
                name=str(payload.get("tool_name") or tool["name"]),
                status=(
                    "failed" if str(payload.get("status") or "") == "error" else "done"
                ),
                result=preview_text(result, limit=400),
            )
        elif event_type == "text_delta":
            self.output_text += str(payload.get("delta") or "")
        elif event_type in {"run_completed", "agent_completed"}:
            self.status = "completed"
            if payload.get("output_text"):
                self.output_text = str(payload["output_text"])
        elif event_type in {"run_failed", "run_cancelled", "run_limit_exceeded", "agent_failed"}:
            self.status = "cancelled" if event_type == "run_cancelled" or payload.get("error_type") == "HarnessCancelled" else "failed"
            if payload.get("message"):
                self.output_text = str(payload["message"])
