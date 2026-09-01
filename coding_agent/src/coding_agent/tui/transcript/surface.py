"""Transcript mounting and follow-tail mixed into CodingAgentApp."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from coding_agent.tui.transcript.messages import AssistantMessage, Notice, Welcome
from coding_agent.tui.transcript.process import ReasoningWidget, RunProcess, ThinkingStatus

LIVE_TOOL_WIDGET_LIMIT = 8


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

    def _mount_transcript(self, widget: Static) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        welcome = self.query(".welcome")
        if welcome:
            welcome.first().remove()
        transcript.mount(widget)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        if new or self._assistant is None:
            self._assistant = AssistantMessage(text)
            self._mount_transcript(self._assistant)
        else:
            transcript = self.query_one("#transcript", VerticalScroll)
            was_at_end = transcript.is_vertical_scroll_end
            self._assistant.set_content(text)
            self._follow_transcript_tail(transcript, was_at_end=was_at_end)

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

    def add_tool(self, call_id: str, name: str) -> None:
        from coding_agent.tui.tools.calls import make_tool_widget

        if self._thinking is not None:
            self._thinking.set_visible(False)
        widget = make_tool_widget(call_id, name)
        self._tools[call_id] = widget
        self._mount_process_item(widget)
        self._cap_live_tools()

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
        elif status == "done":
            widget.set_result(result)
        else:
            widget.set_arguments(arguments, raw_arguments)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)
        if status == "done":
            self._cap_live_tools()

    def _cap_live_tools(self) -> None:
        """Keep only the newest live ToolCallWidgets mounted; older ones join one explored line."""
        from coding_agent.tui.tools.calls import ToolCallWidget

        limit = getattr(self, "live_tool_widget_limit", LIVE_TOOL_WIDGET_LIMIT)
        live_ids = [
            call_id
            for call_id, widget in self._tools.items()
            if isinstance(widget, ToolCallWidget) and widget.tool_name != "spawn_agent"
        ]
        if len(live_ids) <= limit:
            return
        for call_id in live_ids[:-limit]:
            widget = self._tools[call_id]
            if not isinstance(widget, ToolCallWidget):
                continue
            if widget.status in {"preparing", "running"}:
                continue
            self._collapse_tool_widget(call_id)

    def _collapse_tool_widget(self, call_id: str) -> None:
        from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget

        widget = self._tools.get(call_id)
        if not isinstance(widget, ToolCallWidget) or widget.tool_name == "spawn_agent":
            return
        summary = self._adjacent_explored_summary(widget)
        if summary is None:
            summary = ToolCallSummary()
            if self._process is not None:
                self._process.replace_item(widget, summary)
        elif self._process is not None:
            self._process.remove_item(widget)
        summary.add_call(call_id)
        self._tools[call_id] = summary

    def _adjacent_explored_summary(self, widget: Widget) -> Any:
        """Reuse the explored line in this stretch; start a new one after a thought."""
        from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget

        if self._process is None:
            return None
        items = self._process.timeline_items()
        try:
            index = items.index(widget)
        except ValueError:
            return None
        for item in reversed(items[:index]):
            if isinstance(item, ReasoningWidget):
                return None
            if isinstance(item, ToolCallSummary):
                return item
            if isinstance(item, ToolCallWidget):
                return None
        return None

    def add_notice(self, text: str, tone: str = "info") -> None:
        notice = Notice(text, tone)
        if self._busy and self._process is not None:
            self._mount_process_item(notice)
        else:
            self._mount_transcript(notice)

    def finish_process(self, title: str, *, collapse: bool = True) -> None:
        if self._process is not None:
            self._process.complete(title, collapse=collapse)

    def mount_transcript(self, widget: Static) -> None:
        """Public adapter used by the persisted-history loader."""
        self._mount_transcript(widget)

    def action_clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        transcript.mount(Welcome(self.workspace))
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools.clear()
        self._subagents.clear()

