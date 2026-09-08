"""Restore persisted conversation messages into a TUI transcript."""

from __future__ import annotations

import json
from typing import Any, Protocol

from textual.widgets import Static

from coding_agent.agent import CodingAgent
from coding_agent.tui.tools.images import display_from_content
from coding_agent.tui.tools import ToolCallWidget, make_tool_widget
from coding_agent.tui.transcript import UserMessage
from core_ai.content import text_from_content
from core_harness.context import COMPACTED_CONTEXT_MARK, estimate_prompt_tokens

# Older transcript entries remain visible as inexpensive plain widgets. Only
# this recent window gets interactive Markdown/tool-card construction.
HISTORY_ACTIVE_ITEMS = 200


class HistoryView(Protocol):
    def add_notice(self, text: str, tone: str = "info") -> None: ...

    def mount_transcript(self, widget: Any) -> None: ...

    def mount_transcript_batch(self, widgets: list[Any]) -> None: ...

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None: ...

    def finalize_transcript_history(self) -> None: ...


async def load_session_history(agent: CodingAgent, view: HistoryView) -> None:
    """Load the agent's saved messages and mount their transcript widgets."""
    loader = getattr(agent.persistence, "load_transcript", agent.persistence.load_conversation)
    messages = await loader(session_id=agent.session_id)
    context_limit = agent.harness.state.context_limit(agent.harness.model_id)
    view.set_context_metrics(estimate_prompt_tokens(messages), context_limit)
    view.add_notice(f"Resumed session · {agent.session_id}")
    pending_tools: dict[str, ToolCallWidget] = {}
    restored: list[Any] = []
    archive: list[str] = []
    active_start = max(0, len(messages) - HISTORY_ACTIVE_ITEMS)

    for index, message in enumerate(messages):
        if index < active_start:
            if message.role == "user":
                text = text_from_content(message.content)
                if text and not text.startswith(COMPACTED_CONTEXT_MARK):
                    archive.append(f"> {text}")
            elif message.role == "assistant":
                text = text_from_content(message.content)
                if text:
                    archive.append(f"◆  SYMPHONY\n{text}")
                for call in message.tool_calls or []:
                    function = call.get("function") or {}
                    name = function.get("name") or call.get("name") or "tool"
                    archive.append(f"  ✓ {name}")
            elif message.role == "tool":
                result = text_from_content(message.content)
                if result:
                    archive.append(f"  └ {result}")
            continue
        if archive:
            restored.append(Static("\n\n".join(archive), classes="history-archive"))
            archive.clear()
        if message.role == "user":
            # Compaction summaries are internal context-management messages.
            # Keep them in the model history, but do not expose them as user turns.
            if text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK):
                continue
            text, images = display_from_content(message.content)
            restored.append(UserMessage(text, images=images))
        elif message.role == "assistant":
            _restore_assistant_message(
                restored, message, text_from_content(message.content), pending_tools
            )
        elif message.role == "tool":
            widget = pending_tools.get(str(message.tool_call_id))
            if widget:
                widget.set_result(text_from_content(message.content))
                widget.add_class("history-compact")
    mount_batch = getattr(view, "mount_transcript_batch", None)
    if callable(mount_batch):
        mount_batch(restored)
    else:
        for widget in restored:
            view.mount_transcript(widget)
    view.finalize_transcript_history()


def _restore_assistant_message(
    restored: list[Any],
    message: Any,
    content: str,
    pending_tools: dict[str, ToolCallWidget],
) -> None:
    from coding_agent.tui.transcript import AssistantMessage

    if content:
        restored.append(AssistantMessage(content))
    for call in message.tool_calls or []:
        call_id = str(call.get("id") or "history-tool")
        function = call.get("function") or {}
        name = str(function.get("name") or call.get("name") or "tool")
        widget = make_tool_widget(call_id, name)
        raw = function.get("arguments") or call.get("arguments") or ""
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {}
        widget.set_running(args if isinstance(args, dict) else {})
        pending_tools[call_id] = widget
        restored.append(widget)
