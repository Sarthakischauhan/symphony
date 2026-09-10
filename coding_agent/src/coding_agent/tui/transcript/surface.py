"""Transcript mounting and follow-tail mixed into CodingAgentApp."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from textual.containers import VerticalScroll
from textual.widget import Widget

from coding_agent.tui.transcript.live_tools import LIVE_TOOL_WIDGET_LIMIT, reconcile_live_tools
from coding_agent.tui.transcript.archive import TranscriptTurn
from coding_agent.tui.transcript.messages import (
    AssistantMessage,
    Notice,
    RunSummary,
    UserMessage,
    Welcome,
)
from coding_agent.tui.transcript.process import (
    ProcessComplete,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
)


class TranscriptSurface:
    """TranscriptView implementation mixed into CodingAgentApp."""

    def _follow_transcript_tail(
        self, transcript: VerticalScroll, *, was_at_end: bool
    ) -> None:
        """Keep following live output unless the user has scrolled away."""
        if not was_at_end:
            return
        self._pending_scroll_end = True
        if getattr(self, "_scroll_end_scheduled", False):
            return
        self._scroll_end_scheduled = True
        self.call_after_refresh(self._flush_transcript_scroll_end)

    def _flush_transcript_scroll_end(self) -> None:
        self._scroll_end_scheduled = False
        if not getattr(self, "_pending_scroll_end", False):
            return
        self._pending_scroll_end = False
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.scroll_end(animate=False)

    def _mount_transcript(self, widget: Widget) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        welcome = self.query(".welcome")
        if welcome:
            welcome.first().remove()
        if isinstance(widget, UserMessage):
            turn = TranscriptTurn(widget)
            self._transcript_turns.append(turn)
            self._current_transcript_turn = turn
            transcript.mount(widget)
            self._compact_transcript()
        elif self._current_transcript_turn is not None:
            self._current_transcript_turn.add_item(widget)
            transcript.mount(widget)
        else:
            transcript.mount(widget)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def _compact_transcript(self, *, final: bool = False) -> None:
        """Condense completed tool widgets without hiding conversation turns."""
        limit = getattr(self, "live_tool_widget_limit", LIVE_TOOL_WIDGET_LIMIT)
        if limit < 0:
            return

        for turn in self._transcript_turns:
            reconcile_live_tools(turn, limit=limit, final=final)
            for item in turn.timeline_items():
                if isinstance(item, RunProcess):
                    tools = self._tools if item is self._process else None
                    reconcile_live_tools(item, tools, limit=limit, final=final or item.completed)

    def finalize_transcript_history(self) -> None:
        """Apply condensation and freeze completed message renders."""
        self._compact_transcript(final=True)
        for message in self.query(".message"):
            freeze = getattr(message, "freeze_render", None)
            if freeze is not None:
                freeze()

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        if new or self._assistant is None:
            if self._thinking is not None:
                self._thinking.set_visible(False)
            self._assistant = AssistantMessage(text, streaming=True)
            self._mount_transcript(self._assistant)
        else:
            transcript = self.query_one("#transcript", VerticalScroll)
            was_at_end = transcript.is_vertical_scroll_end
            self._assistant.set_content(text, streaming=True)
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def finish_assistant(self) -> None:
        if self._assistant is not None:
            self._assistant.finish_stream()

    def invalidate_workspace_caches(self) -> None:
        index = getattr(self, "_file_index", None)
        if index is not None:
            index.invalidate()
        if hasattr(self, "_plan_list_cache"):
            self._plan_list_cache = None

    def set_thinking(self, text: str) -> None:
        if self._thinking is None:
            self._thinking = ThinkingStatus(text)
            self._process = RunProcess(self._thinking)
            self._mount_transcript(self._process)
        else:
            self._thinking.set_text(text)

    def set_working(self, detail: str = "") -> None:
        if self._thinking is None:
            self.set_thinking("Working")
        assert self._thinking is not None
        self._thinking.set_visible(True)
        self._thinking.set_working(detail)

    def set_churning(self, turn: int = 0) -> None:
        if self._thinking is None:
            self.set_thinking("Churning")
        assert self._thinking is not None
        self._thinking.set_visible(True)
        self._thinking.set_churning(turn)
        if self._process is not None:
            self._process.place_thinking_last()

    def _mount_process_item(self, widget: Widget) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        if self._process is None:
            self.set_thinking("Thinking…")
        assert self._process is not None
        self._process.add_item(widget)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def set_reasoning(self, text: str, *, new: bool = False) -> None:
        if new or self._reasoning is None:
            if self._thinking is not None:
                self._thinking.set_visible(False)
            self._reasoning = ReasoningWidget(text)
            self._mount_process_item(self._reasoning)
        else:
            transcript = self.query_one("#transcript", VerticalScroll)
            was_at_end = transcript.is_vertical_scroll_end
            self._reasoning.set_content(text)
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def finish_reasoning(self) -> None:
        if self._reasoning is None:
            return
        self._reasoning.complete()
        self._reasoning = None
        if self._process is not None:
            reconcile_live_tools(
                self._process,
                self._tools,
                limit=getattr(self, "live_tool_widget_limit", LIVE_TOOL_WIDGET_LIMIT),
                final=self._process.completed,
            )
        self._compact_transcript()

    def add_tool(self, call_id: str, name: str) -> None:
        from coding_agent.tui.tools.calls import make_tool_widget

        if self._thinking is not None:
            self._thinking.set_visible(False)
        widget = make_tool_widget(call_id, name)
        self._tools[call_id] = widget
        self._mount_process_item(widget)

    def update_tool(
        self,
        call_id: str,
        *,
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None:
        from coding_agent.tui.tools.calls import ToolCallSummary

        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        widget = self._tools.get(call_id)
        if widget is None:
            self.add_tool(call_id, "tool")
            widget = self._tools[call_id]
        if isinstance(widget, ToolCallSummary):
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)
            return
        if status == "running":
            widget.set_running(arguments)
        elif status in {"done", "failed"}:
            widget.set_result(result)
            if status == "failed":
                widget.status = "failed"
                widget.refresh_content()
            if widget.tool_name in {"write_file", "patch", "bash"}:
                self.invalidate_workspace_caches()
        else:
            widget.set_arguments(arguments, raw_arguments)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)
        if status in {"done", "failed"}:
            reconcile_live_tools(
                self._process,
                self._tools,
                limit=getattr(self, "live_tool_widget_limit", LIVE_TOOL_WIDGET_LIMIT),
                final=self._process is not None and self._process.completed,
            )
            self._compact_transcript()

    def add_notice(self, text: str, tone: str = "info") -> None:
        notice = Notice(text, tone)
        if self._busy and self._process is not None:
            self._mount_process_item(notice)
        else:
            self._mount_transcript(notice)

    def add_run_summary(
        self,
        summary: str,
        *,
        label: str = "summary so far",
        event_type: str = "run_summary",
    ) -> None:
        widget = RunSummary(summary, label=label, event_type=event_type)
        if self._busy and self._process is not None:
            self._mount_process_item(widget)
        else:
            self._mount_transcript(widget)

    def finish_process(
        self,
        title: str,
        *,
        collapse: bool = True,
        add_completion: bool = True,
    ) -> None:
        if self._process is not None:
            self._process.complete(
                title, collapse=collapse, add_completion=add_completion
            )
            reconcile_live_tools(
                self._process,
                self._tools,
                limit=getattr(self, "live_tool_widget_limit", LIVE_TOOL_WIDGET_LIMIT),
                final=True,
            )
        self._compact_transcript()
        if add_completion and self._process is not None:
            self._mount_transcript(ProcessComplete(title))

    def add_run_completion(self, title: str) -> None:
        """Place compact run metrics after the finalized assistant reply."""
        self._mount_transcript(ProcessComplete(title))

    def mount_transcript(self, widget: Widget) -> None:
        """Public adapter used by the persisted-history loader."""
        self._mount_transcript(widget)

    def mount_transcript_batch(self, widgets: list[Widget]) -> None:
        """Mount restored history in one layout pass instead of one per row."""
        if not widgets:
            return
        transcript = self.query_one("#transcript", VerticalScroll)
        for welcome in self.query(".welcome"):
            welcome.remove()
        for widget in widgets:
            if isinstance(widget, UserMessage):
                turn = TranscriptTurn(widget)
                self._transcript_turns.append(turn)
                self._current_transcript_turn = turn
            elif self._current_transcript_turn is not None:
                self._current_transcript_turn.add_item(widget)
            transcript.mount(widget)
        self._compact_transcript(final=True)

    def action_clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        transcript.mount(Welcome(self.workspace))
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools.clear()
        self._transcript_turns.clear()
        self._current_transcript_turn = None
