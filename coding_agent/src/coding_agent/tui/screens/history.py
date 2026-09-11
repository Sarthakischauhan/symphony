"""Restore persisted conversation messages into a TUI transcript."""

from __future__ import annotations

import json
from typing import Any, Protocol

from coding_agent.agent import CodingAgent
from coding_agent.tui.tools.calls import (
    ToolCallSnapshot,
    ToolCallSummary,
    snapshot_from_call,
)
from coding_agent.tui.tools.images import display_from_content
from coding_agent.tui.transcript import UserMessage
from coding_agent.tui.transcript.live_tools import LIVE_TOOL_WIDGET_LIMIT
from core_ai.content import text_from_content
from core_harness.context import COMPACTED_CONTEXT_MARK, estimate_prompt_tokens


class HistoryView(Protocol):
    def add_notice(self, text: str, tone: str = "info") -> None: ...

    def mount_transcript(self, widget: Any) -> None: ...

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None: ...

    def finalize_transcript_history(self) -> None: ...


async def load_session_history(agent: CodingAgent, view: HistoryView) -> None:
    """Load saved messages as text plus compact Explored rows, not live tool cards."""
    loader = getattr(agent.persistence, "load_transcript", agent.persistence.load_conversation)
    messages = await loader(session_id=agent.session_id)
    # The visual transcript may retain turns that were compacted out of the
    # model context. Footer usage must describe the active context projection,
    # which is what /context reports and what the next request will send.
    context_messages = await agent.persistence.load_conversation(session_id=agent.session_id)
    context_limit = agent.harness.state.context_limit(agent.harness.model_id)
    view.set_context_metrics(estimate_prompt_tokens(context_messages), context_limit)
    view.add_notice(f"Resumed session · {agent.session_id}")

    restored = _history_widgets(messages)
    mount_batch = getattr(view, "mount_transcript_batch", None)
    if callable(mount_batch):
        mount_batch(restored)
    else:
        for widget in restored:
            view.mount_transcript(widget)
    view.finalize_transcript_history()


def _history_widgets(messages: list[Any]) -> list[Any]:
    from coding_agent.tui.transcript import AssistantMessage

    restored: list[Any] = []
    pending: dict[str, dict[str, Any]] = {}
    batch: list[ToolCallSnapshot] = []

    def flush_batch() -> None:
        if not batch:
            return
        restored.append(ToolCallSummary(tuple(batch)))
        batch.clear()

    def add_snapshot(snapshot: ToolCallSnapshot) -> None:
        batch.append(snapshot)
        if len(batch) >= LIVE_TOOL_WIDGET_LIMIT:
            flush_batch()

    for message in messages:
        if message.role == "user":
            if text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK):
                continue
            flush_batch()
            pending.clear()
            text, images = display_from_content(message.content)
            restored.append(UserMessage(text, images=images, enter=False))
        elif message.role == "assistant":
            content = text_from_content(message.content)
            if content:
                restored.append(AssistantMessage(content, enter=False))
            for call in message.tool_calls or []:
                fields = _call_fields(call)
                pending[str(fields["call_id"])] = fields
        elif message.role == "tool":
            call_id = str(message.tool_call_id or "")
            fields = pending.pop(call_id, None) or {
                "call_id": call_id or "history-tool",
                "tool_name": "tool",
                "arguments": {},
                "raw_arguments": "",
            }
            result = text_from_content(message.content)
            add_snapshot(
                snapshot_from_call(
                    **fields,
                    result=result,
                    status="failed" if result.startswith("error:") else "done",
                )
            )

    for fields in pending.values():
        add_snapshot(snapshot_from_call(**fields, status="done"))
    flush_batch()
    return restored


def _call_fields(call: Any) -> dict[str, Any]:
    function = call.get("function") or {}
    raw = function.get("arguments") or call.get("arguments") or ""
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return {
        "call_id": str(call.get("id") or "history-tool"),
        "tool_name": str(function.get("name") or call.get("name") or "tool"),
        "arguments": args,
        "raw_arguments": raw if isinstance(raw, str) else "",
    }
