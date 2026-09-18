"""Capped semantic run state for the critic. Never a raw transcript or JSONL dump."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from core_ai.content import text_from_content
from core_ai.types import Message

from coding_agent.config import EvaluationConfig
from coding_agent.evaluation.protocol import EvaluationPhase

WRITE_TOOLS = frozenset({"write_file", "patch"})
MAX_PLAN_ITEMS = 40
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s+(.*)$")


@dataclass
class PlanItem:
    text: str
    status: str


@dataclass
class RunState:
    """Bounded snapshot sent to the evaluator."""

    phase: EvaluationPhase
    request: str = ""
    brief: str = ""
    plan: str = ""
    plan_items: list[PlanItem] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    last_tool_results: list[str] = field(default_factory=list)
    final: str = ""

    def as_eval_state(self) -> dict[str, Any]:
        """Compact payload for the evaluation-model ``state`` field."""
        return {
            "request": self.request,
            "brief": self.brief,
            "plan": self.plan,
            "plan_items": [
                {"text": item.text, "status": item.status} for item in self.plan_items
            ],
            "observations": self.observations,
            "files_modified": self.files_modified,
            "last_tool_results": self.last_tool_results,
            "final": self.final,
        }


def clip_text(text: str, limit: int) -> str:
    value = text or ""
    if limit <= 0 or len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return value[: limit - 1] + "…"


def clip_lines(lines: Iterable[str], max_chars: int) -> list[str]:
    out: list[str] = []
    used = 0
    for line in lines:
        remaining = max_chars - used
        if remaining <= 0:
            break
        clipped = clip_text(line, remaining)
        if not clipped:
            continue
        out.append(clipped)
        used += len(clipped)
    return out


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return (text or "").strip()


def plan_items_from_markdown(text: str) -> list[PlanItem]:
    items: list[PlanItem] = []
    for line in (text or "").splitlines():
        match = _CHECKBOX.match(line)
        if match is None:
            continue
        status = "done" if match.group(1).strip() else "pending"
        items.append(PlanItem(text=clip_text(match.group(2).strip(), 200), status=status))
    return items


def request_from_messages(messages: Iterable[Message]) -> str:
    for message in reversed(list(messages)):
        if isinstance(message, Message) and message.role == "user":
            return text_from_content(message.content).strip()
    return ""


def _tool_name(call: object) -> str:
    if isinstance(call, dict):
        function = call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "").strip()
        return str(call.get("name") or "").strip()
    return str(getattr(call, "name", "") or "").strip()


def _tool_args(call: object) -> dict[str, Any]:
    raw: Any = None
    if isinstance(call, dict):
        function = call.get("function")
        if isinstance(function, dict):
            raw = function.get("arguments")
        elif "arguments" in call:
            raw = call.get("arguments")
    else:
        raw = getattr(call, "arguments", None)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def files_modified_from_calls(calls: Iterable[object], *, limit: int) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for call in calls:
        if _tool_name(call) not in WRITE_TOOLS:
            continue
        path = str(_tool_args(call).get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def files_modified_from_messages(messages: Iterable[Message], *, limit: int) -> list[str]:
    calls: list[object] = []
    for message in messages:
        if isinstance(message, Message) and message.tool_calls:
            calls.extend(message.tool_calls)
    return files_modified_from_calls(calls, limit=limit)


def observations_from_messages(messages: Iterable[Message]) -> list[str]:
    lines: list[str] = []
    pending: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, Message):
            continue
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                name = _tool_name(call) or "tool"
                args = _tool_args(call)
                detail = str(args.get("path") or args.get("command") or "").strip()
                summary = f"{name} {detail}".strip()
                call_id = ""
                if isinstance(call, dict):
                    call_id = str(call.get("id") or "")
                lines.append(summary)
                if call_id:
                    pending[call_id] = summary
            continue
        if message.role == "tool":
            body = text_from_content(message.content).strip()
            failed = body.startswith("[tool:")
            status = "error" if failed else "ok"
            key = message.tool_call_id or ""
            prefix = pending.get(key) or "tool"
            lines.append(f"{prefix} → {status}")
    return lines


def last_tool_results_from_messages(messages: Iterable[Message], *, max_items: int = 5) -> list[str]:
    results: list[str] = []
    for message in messages:
        if isinstance(message, Message) and message.role == "tool":
            results.append(text_from_content(message.content).strip())
    return results[-max_items:]


def build_run_state(
    *,
    config: EvaluationConfig,
    phase: EvaluationPhase,
    request: str = "",
    messages: Optional[Iterable[Message]] = None,
    plan_text: str = "",
    final: str = "",
    tool_calls: Optional[Iterable[object]] = None,
) -> RunState:
    """Assemble a capped semantic snapshot. Caps apply per field."""
    message_list = list(messages or [])
    request_text = request.strip() or request_from_messages(message_list)
    items = plan_items_from_markdown(plan_text)
    files = files_modified_from_calls(tool_calls or (), limit=config.files_modified_max)
    if not files:
        files = files_modified_from_messages(message_list, limit=config.files_modified_max)
    return RunState(
        phase=phase,
        request=clip_text(request_text, config.request_max_chars),
        brief=clip_text(first_line(request_text), config.brief_max_chars),
        plan=clip_text(plan_text, config.plan_max_chars),
        plan_items=items[:MAX_PLAN_ITEMS],
        observations=clip_lines(
            observations_from_messages(message_list), config.observations_max_chars
        ),
        files_modified=files,
        last_tool_results=clip_lines(
            last_tool_results_from_messages(message_list),
            config.last_tool_results_max_chars,
        ),
        final=clip_text(final, config.final_max_chars),
    )


__all__ = [
    "PlanItem",
    "RunState",
    "WRITE_TOOLS",
    "build_run_state",
    "clip_lines",
    "clip_text",
    "files_modified_from_calls",
    "files_modified_from_messages",
    "first_line",
    "last_tool_results_from_messages",
    "observations_from_messages",
    "plan_items_from_markdown",
    "request_from_messages",
]
