"""Map harness events into durable conversation components."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from coding_agent.tui.state import UiRunState
from coding_agent.utils.text import preview_text

StatusFn = Callable[[str], None]


class TranscriptView(Protocol):
    """Small rendering boundary, deliberately free of Textual types."""

    def set_assistant(self, text: str, *, new: bool = False) -> None: ...

    def set_thinking(self, text: str) -> None: ...

    def set_reasoning(self, text: str, *, new: bool = False) -> None: ...

    def finish_process(self, title: str, *, collapse: bool = True) -> None: ...

    def add_tool(self, call_id: str, name: str) -> None: ...

    def update_tool(
        self,
        call_id: str,
        *,
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None: ...

    def add_notice(self, text: str, tone: str = "info") -> None: ...


class EventPresenter:
    """Stateful event reducer that updates a transcript view."""

    def __init__(
        self,
        *,
        state: UiRunState,
        view: TranscriptView,
        set_status: StatusFn,
        workspace: str = "",
    ) -> None:
        self.state = state
        self.view = view
        self._set_status = set_status
        self.workspace = workspace
        self._assistant_open = False
        self._tool_names: dict[str, str] = {}
        self._tool_arguments: dict[str, str] = {}
        self._reasoning_summaries: set[tuple[int, int]] = set()

    def refresh_chrome(self) -> None:
        self._set_status(self.state.status_line(workspace=self.workspace))

    def handle(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        payload = payload or {}
        handler = getattr(self, f"_on_{event_type}", None)
        if handler is None:
            self.view.add_notice(f"{event_type} · {preview_text(payload)}")
        else:
            handler(payload)
        self.refresh_chrome()

    def flush_stream_to_log(self) -> None:
        """Compatibility name: streamed content already updates in place."""
        self._assistant_open = False

    def _usage_text(self, prefix: str = "Thinking") -> str:
        m = self.state.metrics
        if not (m.prompt_tokens or m.completion_tokens):
            turn = f" · turn {self.state.turn + 1}" if self.state.turn is not None else ""
            return f"{prefix}{turn}"
        estimate = "~" if m.estimated else ""
        text = (
            f"{prefix} · {estimate}{m.prompt_tokens:,} in / "
            f"{estimate}{m.completion_tokens:,} out"
        )
        if m.reasoning_tokens:
            text += f" · {m.reasoning_tokens:,} reasoning"
        return text

    # Run lifecycle
    def _on_run_started(self, payload: Dict[str, Any]) -> None:
        self.state.reset_for_run(model_id=str(payload.get("model_id") or self.state.model_id))
        self._assistant_open = False
        self._tool_names.clear()
        self._tool_arguments.clear()
        self._reasoning_summaries.clear()
        self.view.set_thinking("Thinking…")

    def _on_run_completed(self, payload: Dict[str, Any]) -> None:
        usage = payload.get("usage") or {}
        context = payload.get("context") or {}
        if usage:
            self.state.update_usage(
                {
                    **usage,
                    "cumulative_tokens": usage.get("total_tokens", 0),
                    "estimated": False,
                }
            )
        if context:
            self.state.update_context(context)
        self.state.phase = "idle"
        self.state.detail = "ready"
        completed = self._completed_text()
        self.view.set_thinking(completed)
        self.view.finish_process(completed)
        self._assistant_open = False

    def _completed_text(self) -> str:
        m = self.state.metrics
        current = f"{m.tokens_used:,} context" if m.tokens_used else "context unknown"
        cumulative = (
            f"{m.cumulative_tokens:,} cumulative input"
            if m.cumulative_tokens
            else "input unknown"
        )
        output = f"{m.completion_tokens:,} out"
        if m.reasoning_tokens:
            output += f" · {m.reasoning_tokens:,} reasoning"
        return f"Completed · {current} · {cumulative} · {output}"

    def _on_run_failed(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "idle"
        self.state.detail = "failed"
        self.view.set_thinking("Stopped with an error")
        self.view.add_notice(str(payload.get("message") or payload), "error")
        self.view.finish_process("Stopped with an error", collapse=False)

    def _on_run_cancelled(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "idle"
        self.state.detail = "cancelled"
        self.view.set_thinking("Cancelled")
        reason = payload.get("reason")
        if reason:
            self.view.add_notice(str(reason), "warning")
        self.view.finish_process("Cancelled")

    # Turns and streaming
    def _on_turn_started(self, payload: Dict[str, Any]) -> None:
        turn = int(payload.get("turn") or 0)
        self.state.begin_turn(turn)
        self._assistant_open = False
        self.view.set_thinking(self._usage_text())

    def _on_turn_completed(self, payload: Dict[str, Any]) -> None:
        self.state.detail = "running tools" if payload.get("had_tool_calls") else "finishing"
        if not payload.get("had_tool_calls"):
            self._assistant_open = False

    def _on_text_delta(self, payload: Dict[str, Any]) -> None:
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        is_new = not self._assistant_open
        if is_new:
            self.state.stream_text = ""
        self.state.append_text(delta)
        self.view.set_assistant(self.state.stream_text, new=is_new)
        self._assistant_open = True

    def _on_reasoning_delta(self, payload: Dict[str, Any]) -> None:
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        key = (
            int(payload.get("turn") or 0),
            int(payload.get("summary_index") or 0),
        )
        is_new = key not in self._reasoning_summaries
        self._reasoning_summaries.add(key)
        text = str(payload.get("text") or delta)
        self.state.reasoning_text = text
        self.state.phase = "thinking"
        self.state.detail = "reasoning"
        self.view.set_reasoning(text, new=is_new)

    # Tools
    def _on_tool_call_started(self, payload: Dict[str, Any]) -> None:
        self._assistant_open = False
        call_id = str(payload.get("tool_call_id") or "tool")
        name = str(payload.get("tool_name") or "tool")
        self._tool_names[call_id] = name
        self._tool_arguments[call_id] = ""
        self.state.phase = "tool"
        self.state.detail = f"preparing {name}"
        self.view.add_tool(call_id, name)

    def _on_tool_call_delta(self, payload: Dict[str, Any]) -> None:
        call_id = str(payload.get("tool_call_id") or "tool")
        raw = self._tool_arguments.get(call_id, "") + str(payload.get("delta") or "")
        self._tool_arguments[call_id] = raw
        self.state.phase = "tool"
        self.state.tool_args_preview = raw[-80:]
        arguments: Optional[dict[str, Any]] = None
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                arguments = decoded
        except json.JSONDecodeError:
            pass
        self.view.update_tool(call_id, arguments=arguments, raw_arguments=raw)

    def _on_tool_execution_started(self, payload: Dict[str, Any]) -> None:
        call_id = str(payload.get("tool_call_id") or "tool")
        name = str(payload.get("tool_name") or self._tool_names.get(call_id, "tool"))
        if call_id not in self._tool_names:
            self._tool_names[call_id] = name
            self.view.add_tool(call_id, name)
        self.state.phase = "tool"
        self.state.detail = f"running {name}"
        self.view.update_tool(call_id, arguments=payload.get("arguments") or {}, status="running")

    def _on_tool_execution_completed(self, payload: Dict[str, Any]) -> None:
        call_id = str(payload.get("tool_call_id") or "tool")
        self.state.phase = "thinking"
        self.state.detail = f"finished {payload.get('tool_name') or 'tool'}"
        self.view.update_tool(call_id, status="done", result=payload.get("result", ""))

    # Metrics and context
    def _on_usage(self, payload: Dict[str, Any]) -> None:
        self.state.update_usage(payload)
        if self.state.metrics.reasoning_tokens and not self._reasoning_summaries:
            self.view.set_reasoning(
                "Reasoning was used, but the API did not include a reasoning summary.",
                new=True,
            )
        self.view.set_thinking(self._usage_text())

    def _on_context(self, payload: Dict[str, Any]) -> None:
        self.state.update_context(payload)

    def _on_context_warning(self, payload: Dict[str, Any]) -> None:
        left = payload.get("context_left")
        message = (
            f"Context is running low · {left:,} tokens left"
            if isinstance(left, int)
            else "Context is running low"
        )
        self.view.add_notice(message, "warning")

    def _on_compaction_started(self, payload: Dict[str, Any]) -> None:
        self.state.detail = "compacting context"
        self.view.add_notice("Compacting conversation context…")

    def _on_compaction_completed(self, payload: Dict[str, Any]) -> None:
        before = payload.get("message_count_before", "?")
        after = payload.get("message_count_after", "?")
        self.view.add_notice(f"Compacted context · {before} → {after} messages", "success")

    def _on_paused(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "paused"
        self.state.detail = "paused"
        self.view.set_thinking("Paused")

    def _on_resumed(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "thinking"
        self.state.detail = "resumed"
        self.view.set_thinking("Resuming…")

    def _on_message_injected(self, payload: Dict[str, Any]) -> None:
        role = payload.get("role", "user")
        content = preview_text(payload.get("content", ""))
        self.view.add_notice(f"Injected {role} message · {content}")

    def _on_question_asked(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "paused"
        self.state.detail = "waiting for user"
        question = str(payload.get("question") or "")
        self.view.add_notice(f"Question · {preview_text(question)}", "warning")
