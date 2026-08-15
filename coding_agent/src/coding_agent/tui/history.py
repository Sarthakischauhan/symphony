"""Restore persisted conversation messages into a TUI transcript."""

from __future__ import annotations

import json
from typing import Any, Protocol

from coding_agent.agent import CodingAgent
from coding_agent.tui.widgets import ToolCallWidget, UserMessage, make_tool_widget
from core_harness.utils.tokens import estimate_prompt_tokens


class HistoryView(Protocol):
    def add_notice(self, text: str, tone: str = "info") -> None: ...

    def mount_transcript(self, widget: Any) -> None: ...

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None: ...


async def load_session_history(agent: CodingAgent, view: HistoryView) -> None:
    """Load the agent's saved messages and mount their transcript widgets."""
    messages = await agent.persistence.load_conversation(session_id=agent.session_id)
    context_limit = agent.harness.state.context_limit(agent.harness.model_id)
    view.set_context_metrics(estimate_prompt_tokens(messages), context_limit)
    view.add_notice(f"Resumed session · {agent.session_id}")
    pending_tools: dict[str, ToolCallWidget] = {}

    for message in messages:
        content = _message_content(message.content)
        if message.role == "user":
            view.mount_transcript(UserMessage(content))
        elif message.role == "assistant":
            _restore_assistant_message(view, message, content, pending_tools)
        elif message.role == "tool":
            widget = pending_tools.get(str(message.tool_call_id))
            if widget:
                widget.set_result(content)


def _message_content(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _restore_assistant_message(
    view: HistoryView,
    message: Any,
    content: str,
    pending_tools: dict[str, ToolCallWidget],
) -> None:
    from coding_agent.tui.widgets import AssistantMessage

    if content:
        view.mount_transcript(AssistantMessage(content))
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
        view.mount_transcript(widget)
