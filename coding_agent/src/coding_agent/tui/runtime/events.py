"""Map harness events into durable conversation components."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

from coding_agent.tui.runtime.state import UiRunState
from coding_agent.tui.transcript.messages import preview_text

StatusFn = Callable[[str], None]
ScheduleFlush = Callable[[Callable[[], None]], None]
ChromeSnapshot = Tuple[Any, ...]

# High-frequency events are reduced immediately but painted on one throttled UI tick.
_BUFFERED_PAINT_EVENT_TYPES = frozenset(
    {"text_delta", "reasoning_delta", "tool_call_delta"}
)


def _clean_reasoning(text: str) -> str:
    """Remove provider labels that duplicate the UI's Thought disclosure."""
    return re.sub(
        r"^\s*(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?\s*"
        r"reasoning summary\s*(?:\*{1,2}|_{1,2})?\s*\n+",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )


def _compaction_notice(payload: Mapping[str, Any]) -> str:
    """Notice text with message counts and, when known, estimated token counts."""
    before = payload.get("message_count_before", "?")
    after = payload.get("message_count_after", "?")
    text = f"Compacted context · {before} → {after} messages"
    tokens_before = payload.get("estimated_tokens_before")
    tokens_after = payload.get("estimated_tokens_after")
    if isinstance(tokens_before, int) and isinstance(tokens_after, int):
        text += f" · ~{tokens_before:,} → ~{tokens_after:,} tokens"
    return text


class TranscriptView(Protocol):
    """Small rendering boundary, deliberately free of Textual types."""

    def set_assistant(self, text: str, *, new: bool = False) -> None: ...

    def finish_assistant(self) -> None: ...

    def set_thinking(self, text: str) -> None: ...

    def set_working(self, detail: str = "") -> None: ...

    def set_reasoning(self, text: str, *, new: bool = False) -> None: ...

    def finish_reasoning(self) -> None: ...

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

    def add_run_summary(
        self,
        summary: str,
        *,
        label: str = "summary so far",
        event_type: str = "run_summary",
    ) -> None: ...


class EventPresenter:
    """Stateful event reducer that updates a transcript view."""

    def __init__(
        self,
        *,
        state: UiRunState,
        view: TranscriptView,
        set_status: StatusFn,
        workspace: str = "",
        schedule_flush: Optional[ScheduleFlush] = None,
    ) -> None:
        self.state = state
        self.view = view
        self._set_status = set_status
        self.workspace = workspace
        self._schedule_flush = schedule_flush
        self._assistant_open = False
        self._tool_names: dict[str, str] = {}
        self._tool_argument_chunks: dict[str, list[str]] = {}
        self._tool_argument_tails: dict[str, str] = {}
        self._reasoning_parts: dict[int, str] = {}
        self._reasoning_active = False
        self._pending_assistant: Optional[tuple[str, bool]] = None
        self._pending_reasoning: Optional[tuple[str, bool]] = None
        self._pending_tool_paints: dict[str, None] = {}
        self._flush_scheduled = False
        self._last_chrome: Optional[ChromeSnapshot] = None

    def _chrome_snapshot(self) -> ChromeSnapshot:
        m = self.state.metrics
        return (
            self.state.phase,
            self.state.detail,
            self.state.status_line(workspace=self.workspace),
            m.prompt_tokens,
            m.completion_tokens,
            m.reasoning_tokens,
            m.total_tokens,
            m.cumulative_tokens,
            m.tokens_used,
            m.context_limit,
            m.context_left,
            m.utilization,
            m.estimated,
        )

    def refresh_chrome(self) -> None:
        snapshot = self._chrome_snapshot()
        if snapshot == self._last_chrome:
            return
        self._last_chrome = snapshot
        self._set_status(self.state.status_line(workspace=self.workspace))

    def handle(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        payload = payload or {}
        before = self._chrome_snapshot()
        if event_type not in _BUFFERED_PAINT_EVENT_TYPES:
            self.flush_stream_paints()
        handler = getattr(self, f"_on_{event_type}", None)
        if handler is None:
            self.view.add_notice(f"{event_type} · {preview_text(payload)}")
        else:
            handler(payload)
        if event_type in _BUFFERED_PAINT_EVENT_TYPES:
            self._request_stream_flush()
        after = self._chrome_snapshot()
        if after != before:
            self.refresh_chrome()

    def flush_stream_to_log(self) -> None:
        """Paint any buffered stream text, then close the live assistant widget."""
        self.flush_stream_paints()
        self.view.finish_assistant()
        self._assistant_open = False

    def flush_stream_paints(self) -> None:
        """Apply buffered assistant/reasoning widget updates."""
        self._flush_scheduled = False
        pending_reasoning = self._pending_reasoning
        pending_assistant = self._pending_assistant
        self._pending_reasoning = None
        self._pending_assistant = None
        pending_tools = tuple(self._pending_tool_paints)
        self._pending_tool_paints.clear()
        if pending_reasoning is not None:
            text, new = pending_reasoning
            self.view.set_reasoning(text, new=new)
        if pending_assistant is not None:
            text, new = pending_assistant
            self.view.set_assistant(text, new=new)
        for call_id in pending_tools:
            raw = "".join(self._tool_argument_chunks.get(call_id, ()))
            arguments: Optional[dict[str, Any]] = None
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    arguments = decoded
            except json.JSONDecodeError:
                pass
            self.view.update_tool(call_id, arguments=arguments, raw_arguments=raw)

    def _request_stream_flush(self) -> None:
        """Schedule one paint for all deltas received during this interval."""
        if (
            self._pending_assistant is None
            and self._pending_reasoning is None
            and not self._pending_tool_paints
        ):
            return
        if self._schedule_flush is None:
            self.flush_stream_paints()
            return
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self._schedule_flush(self.flush_stream_paints)

    def _buffer_assistant(self, text: str, *, new: bool) -> None:
        if self._pending_assistant is None:
            self._pending_assistant = (text, new)
            return
        _, was_new = self._pending_assistant
        self._pending_assistant = (text, was_new or new)

    def _buffer_reasoning(self, text: str, *, new: bool) -> None:
        if self._pending_reasoning is None:
            self._pending_reasoning = (text, new)
            return
        _, was_new = self._pending_reasoning
        self._pending_reasoning = (text, was_new or new)

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
        self._tool_argument_chunks.clear()
        self._tool_argument_tails.clear()
        self._reasoning_parts.clear()
        self._reasoning_active = False
        self._pending_assistant = None
        self._pending_reasoning = None
        self._pending_tool_paints.clear()
        self._flush_scheduled = False
        self.view.set_thinking("Thinking…")

    def _on_run_completed(self, payload: Dict[str, Any]) -> None:
        self._finish_reasoning()
        self.view.finish_assistant()
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

    def _on_run_summary(self, payload: Dict[str, Any]) -> None:
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            return
        label = str(payload.get("label") or "summary so far").strip() or "summary so far"
        self.view.add_run_summary(summary, label=label, event_type="run_summary")

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
        self._finish_reasoning()
        self.state.phase = "idle"
        self.state.detail = "failed"
        self.view.set_thinking("Stopped with an error")
        self.view.add_notice(str(payload.get("message") or payload), "error")
        self.view.finish_process("Stopped with an error", collapse=False)

    def _on_run_cancelled(self, payload: Dict[str, Any]) -> None:
        self._finish_reasoning()
        self.state.phase = "idle"
        self.state.detail = "cancelled"
        self.view.set_thinking("Cancelled")
        reason = payload.get("reason")
        if reason:
            self.view.add_notice(str(reason), "warning")
        self.view.finish_process("Cancelled")

    def _on_run_limit_exceeded(self, payload: Dict[str, Any]) -> None:
        self._finish_reasoning()
        self.state.phase = "idle"
        self.state.detail = "limit exceeded"
        limit = payload.get("limit") or "run limit"
        message = str(payload.get("message") or f"Harness exceeded {limit}")
        self.view.set_thinking("Stopped at a run limit")
        self.view.add_notice(message, "warning")
        self.view.finish_process("Stopped at a run limit", collapse=False)

    # Turns and streaming
    def _on_turn_started(self, payload: Dict[str, Any]) -> None:
        turn = int(payload.get("turn") or 0)
        self.state.begin_turn(turn)
        self._assistant_open = False
        self.view.set_thinking(self._usage_text())

    def _on_turn_completed(self, payload: Dict[str, Any]) -> None:
        self._finish_reasoning()
        self.state.detail = "running tools" if payload.get("had_tool_calls") else "finishing"
        if not payload.get("had_tool_calls"):
            self.view.finish_assistant()
            self._assistant_open = False

    def _on_model_retry_scheduled(self, payload: Dict[str, Any]) -> None:
        retry_after = float(payload.get("retry_after") or 0.0)
        attempt = int(payload.get("attempt") or 1)
        reason = str(payload.get("reason") or "rate_limit")
        if payload.get("resets_stream"):
            self._pending_assistant = None
            self._pending_reasoning = None
            if self._reasoning_active:
                self.view.set_reasoning("")
            self._finish_reasoning()
            self._reasoning_parts.clear()
            self.state.stream_text = ""
            self.state.reasoning_text = ""
            if self._assistant_open:
                self.view.set_assistant("")
        delay = (
            f"{retry_after:.1f}s"
            if retry_after < 10 and not retry_after.is_integer()
            else f"{retry_after:.0f}s"
        )
        self.state.phase = "thinking"
        labels = {
            "rate_limit": "rate limited",
            "ssl_mac_error": "SSL MAC error",
            "ssl_error": "SSL error",
            "server_error": "server error",
            "stream_error": "stream error",
            "connection_error": "connection error",
            "timeout": "timed out",
        }
        label = labels.get(reason, reason.replace("_", " "))
        self.state.detail = f"{label}; retrying in {delay}"
        working = label[0].upper() + label[1:] if label else label
        self.view.set_working(
            f"{working} · retrying in {delay} · attempt {attempt}"
        )

    def _on_text_delta(self, payload: Dict[str, Any]) -> None:
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        self._finish_reasoning()
        is_new = not self._assistant_open
        if is_new:
            self.state.stream_text = ""
        self.state.append_text(delta)
        self._assistant_open = True
        self._buffer_assistant(self.state.stream_text, new=is_new)

    def _on_reasoning_delta(self, payload: Dict[str, Any]) -> None:
        delta = str(payload.get("delta") or "")
        if not delta:
            return
        index = int(payload.get("summary_index") or 0)
        is_new = not self._reasoning_active
        self._reasoning_active = True
        self._reasoning_parts[index] = _clean_reasoning(
            str(payload.get("text") or delta)
        )
        text = "\n\n".join(
            self._reasoning_parts[key] for key in sorted(self._reasoning_parts)
        )
        self.state.reasoning_text = text
        self.state.phase = "thinking"
        self.state.detail = "reasoning"
        self._buffer_reasoning(text, new=is_new)

    def _finish_reasoning(self) -> None:
        pending = self._pending_reasoning
        if pending is not None:
            self._pending_reasoning = None
            text, new = pending
            self.view.set_reasoning(text, new=new)
        if not self._reasoning_active:
            return
        self.view.finish_reasoning()
        self._reasoning_active = False
        self._reasoning_parts.clear()

    # Tools
    def _on_tool_call_started(self, payload: Dict[str, Any]) -> None:
        self._finish_reasoning()
        self.view.finish_assistant()
        self._assistant_open = False
        call_id = str(payload.get("tool_call_id") or "tool")
        name = str(payload.get("tool_name") or "tool")
        self._tool_names[call_id] = name
        self._tool_argument_chunks[call_id] = []
        self._tool_argument_tails[call_id] = ""
        self.state.phase = "tool"
        self.state.detail = f"preparing {name}"
        self.view.add_tool(call_id, name)

    def _on_tool_call_delta(self, payload: Dict[str, Any]) -> None:
        call_id = str(payload.get("tool_call_id") or "tool")
        delta = str(payload.get("delta") or "")
        self._tool_argument_chunks.setdefault(call_id, []).append(delta)
        tail = (self._tool_argument_tails.get(call_id, "") + delta)[-80:]
        self._tool_argument_tails[call_id] = tail
        self.state.phase = "tool"
        self.state.tool_args_preview = tail
        self._pending_tool_paints[call_id] = None

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
        status = "failed" if payload.get("status") in {"error", "cancelled", "timeout"} else "done"
        self.view.update_tool(call_id, status=status, result=payload.get("result", ""))
        self._tool_argument_chunks.pop(call_id, None)
        self._tool_argument_tails.pop(call_id, None)

    # Metrics and context
    def _on_usage(self, payload: Dict[str, Any]) -> None:
        self.state.update_usage(payload)
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
        self.state.update_after_compaction(payload)
        if payload.get("manual"):
            self.state.detail = "ready"
        self.view.add_notice(_compaction_notice(payload), "success")

    def _on_paused(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "paused"
        self.state.detail = "paused"
        self.view.set_thinking("Paused")

    def _on_resumed(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "thinking"
        self.state.detail = "resumed"
        self.view.set_thinking("Resuming…")

    def _on_message_injected(self, payload: Dict[str, Any]) -> None:
        if payload.get("source") == "subagent":
            return  # The child's lifecycle card already presents this result.
        role = payload.get("role", "user")
        content = preview_text(payload.get("content", ""))
        self.view.add_notice(f"Injected {role} message · {content}")

    def _on_waiting_for_children(self, payload: Dict[str, Any]) -> None:
        count = len(payload.get("child_ids") or [])
        self.state.phase = "waiting"
        self.state.detail = f"waiting for {count} subagent{'s' if count != 1 else ''}"
        self.view.set_working(self.state.detail)

    def _on_question_asked(self, payload: Dict[str, Any]) -> None:
        self.state.phase = "paused"
        self.state.detail = "waiting for user"
        question = str(payload.get("question") or "")
        self.view.add_notice(f"Question · {preview_text(question)}", "warning")
