"""Translate between Symphony's event stream and Agent Client Protocol shapes.

Pure functions: no I/O and no agent. ``server`` does the talking.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

from core_harness import HarnessLimitExceeded

PROTOCOL_VERSION = 1

TOOL_KINDS = {
    "read_file": "read",
    "write_file": "edit",
    "patch": "edit",
    "bash": "execute",
    "search": "search",
    "spawn_agent": "think",
}
# How an answer choice reads to a client that only knows ACP option kinds.
OPTION_KINDS = {
    "allow once": "allow_once",
    "allow": "allow_once",
    "always allow": "allow_always",
    "deny": "reject_once",
    "decline": "reject_once",
}
STOP_FOR_LIMIT = {"max_turns": "max_turn_requests", "max_tokens": "max_tokens"}


def _text(text: Any) -> Dict[str, Any]:
    return {"type": "text", "text": str(text)}


def _raw_input(arguments: Any) -> Dict[str, Any] | None:
    """Tool arguments as an object. Providers send them as a JSON string."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    return dict(arguments) if isinstance(arguments, Mapping) else None


def session_updates(event_type: str, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The ``session/update`` bodies for one Symphony event. Often none.

    Only the root agent is narrated. A subagent shows up as the parent's
    ``spawn_agent`` tool call, not as a second voice in the same message.
    """
    if payload.get("parent_id"):
        return []
    if event_type == "text_delta":
        return [{"sessionUpdate": "agent_message_chunk", "content": _text(payload.get("delta") or "")}]
    if event_type == "reasoning_delta":
        return [{"sessionUpdate": "agent_thought_chunk", "content": _text(payload.get("delta") or "")}]
    if event_type == "message_injected" and payload.get("source") == "user":
        content = payload.get("content")
        return [{"sessionUpdate": "user_message_chunk", "content": _text(content if isinstance(content, str) else "")}]
    call_id = str(payload.get("tool_call_id") or "")
    if event_type == "tool_call_started" and call_id:
        name = str(payload.get("tool_name") or "tool")
        return [{
            "sessionUpdate": "tool_call",
            "toolCallId": call_id,
            "title": name,
            "kind": TOOL_KINDS.get(name, "other"),
            "status": "pending",
        }]
    if event_type == "tool_call_arguments" and call_id:
        raw = _raw_input(payload.get("arguments"))
        return [] if raw is None else [{"sessionUpdate": "tool_call_update", "toolCallId": call_id, "rawInput": raw}]
    if event_type == "tool_execution_started" and call_id:
        update: Dict[str, Any] = {"sessionUpdate": "tool_call_update", "toolCallId": call_id, "status": "in_progress"}
        raw = _raw_input(payload.get("arguments"))
        if raw is not None:
            update["rawInput"] = raw
        return [update]
    if event_type == "tool_execution_completed" and call_id:
        result = str(payload.get("result") or "")
        return [{
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": "failed" if payload.get("status") == "error" else "completed",
            "content": [{"type": "content", "content": _text(result)}],
            "rawOutput": {"result": result, "truncated": bool(payload.get("truncated"))},
        }]
    if event_type == "context":
        used, size = payload.get("tokens_used"), payload.get("context_limit")
        if isinstance(used, int) and isinstance(size, int):
            return [{"sessionUpdate": "usage_update", "used": used, "size": size}]
    return []


def permission_request(session_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """``session/request_permission`` params for a ``question_asked`` event.

    Option ids are the choice's position, so the reply maps back exactly.
    """
    choices = [str(choice) for choice in payload.get("choices") or []]
    tool_call: Dict[str, Any] = {
        "toolCallId": str(payload.get("tool_call_id") or payload.get("request_id") or ""),
        "title": str(payload.get("question") or ""),
    }
    return {
        "sessionId": session_id,
        "toolCall": tool_call,
        "options": [
            {"optionId": str(index), "name": choice, "kind": OPTION_KINDS.get(choice.casefold(), "allow_once")}
            for index, choice in enumerate(choices)
        ],
    }


def permission_answer(outcome: Any, payload: Mapping[str, Any]) -> str:
    """The answer string for a client's permission outcome.

    A cancelled or unreadable outcome denies an approval and takes the
    default for any other question.
    """
    choices = [str(choice) for choice in payload.get("choices") or []]
    fallback = "Deny" if payload.get("kind") == "approval" else str(payload.get("default") or "")
    if not isinstance(outcome, Mapping) or outcome.get("outcome") != "selected":
        return fallback
    try:
        return choices[int(str(outcome.get("optionId")))]
    except (ValueError, IndexError):
        return fallback


def prompt_text(blocks: Sequence[Any]) -> str:
    """Flatten ACP content blocks to the text Symphony runs on."""
    parts: List[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource_link":
            parts.append(str(block.get("uri") or ""))
        elif kind == "resource":
            resource = block.get("resource")
            if isinstance(resource, Mapping) and isinstance(resource.get("text"), str):
                parts.append(f"{resource.get('uri') or ''}\n{resource['text']}".strip())
    return "\n\n".join(part for part in parts if part)


def stop_reason_for_limit(error: HarnessLimitExceeded) -> str:
    return STOP_FOR_LIMIT.get(str(error.limit), "end_turn")


__all__ = [
    "PROTOCOL_VERSION",
    "permission_answer",
    "permission_request",
    "prompt_text",
    "session_updates",
    "stop_reason_for_limit",
]
