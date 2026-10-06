"""Transcript mounting mixed into CodingAgentApp.

Every transcript entry is mounted once and then updated in place. Groupable
tool calls become rows of one ``ToolCallSummary`` per consecutive stretch (the
render-time grouping fx does in ``tool_group_projection.zig``), so a status
change only re-renders that group's text. Following the newest output is
Textual's scroll anchor on ``#transcript``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from textual import events
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.widget import Widget

from coding_agent.tui.chrome.footer import ComposerOverlay
from coding_agent.tui.transcript.messages import (
    AssistantMessage,
    Notice,
    RunSummary,
    SelectableStatic,
    Welcome,
)
from coding_agent.tui.transcript.process import (
    ProcessComplete,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
)

if TYPE_CHECKING:
    # tools.* imports transcript.messages, so the runtime imports stay local.
    from coding_agent.tui.tools.calls import ToolCallWidget
    from coding_agent.tui.tools.snapshots import ToolCallSnapshot, ToolCallSummary


class TranscriptScroll(VerticalScroll):
    """The transcript viewport: anchored to its newest content.

    Textual keeps an anchored widget at the bottom through every layout,
    releases the anchor when the reader scrolls up, and restores it when they
    scroll back to the end.
    """

    def on_mount(self) -> None:
        self.anchor()

    @property
    def scroll_offset(self) -> Offset:
        """Keep short transcripts top-aligned while anchored.

        While anchored, Textual parks ``scroll_y`` at ``content - viewport``,
        which is negative until the transcript fills the screen and would push
        the first rows down to the composer.
        """
        offset = super().scroll_offset
        return Offset(offset.x, max(0, offset.y))


class TranscriptSurface:
    """TranscriptView implementation mixed into CodingAgentApp."""

    def _mount_transcript(self, widget: Widget) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        welcome = self.query(".welcome")
        if welcome:
            welcome.first().remove()
        transcript.mount(widget)

    def finalize_transcript_history(self) -> None:
        """Freeze completed message renders after restoring history."""
        for message in self.query(".message"):
            if isinstance(message, SelectableStatic):
                message.freeze_render()

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        if new or self._assistant is None:
            if self._thinking is not None:
                self._thinking.set_visible(False)
            self._assistant = AssistantMessage(text, streaming=True)
            # Keep assistant text in the run timeline so tools and text stay in
            # stream order: a later non-tool widget can close the open stretch.
            if self._process is not None and not self._process.completed:
                self._mount_process_item(self._assistant)
            else:
                self._mount_transcript(self._assistant)
        else:
            self._assistant.set_content(text, streaming=True)

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
        """Append a run timeline entry; anything but a tool row ends the open group."""
        if self._process is None:
            self.set_thinking("Thinking…")
        assert self._process is not None
        self._close_tool_group()
        self._process.add_item(widget)

    def _close_tool_group(self) -> None:
        if self._open_tool_group is not None:
            self._open_tool_group.close()
            self._open_tool_group = None

    def set_reasoning(self, text: str, *, new: bool = False) -> None:
        if new or self._reasoning is None:
            if self._thinking is not None:
                self._thinking.set_visible(False)
            self._reasoning = ReasoningWidget(text)
            self._mount_process_item(self._reasoning)
        else:
            self._reasoning.set_content(text)

    def finish_reasoning(self) -> None:
        if self._reasoning is None:
            return
        self._reasoning.complete()
        self._reasoning = None

    def add_tool(self, call_id: str, name: str) -> None:
        self._show_tool(self._new_tool(call_id, name))

    def _new_tool(self, call_id: str, name: str) -> ToolCallWidget:
        from coding_agent.tui.tools.calls import make_tool_widget

        if self._thinking is not None:
            self._thinking.set_visible(False)
        tool = make_tool_widget(call_id, name, workspace=self.workspace)
        self._tools[call_id] = tool
        return tool

    def _show_tool(self, tool: ToolCallWidget) -> None:
        """Mount an interactive card once, or place/update a row in its group."""
        if tool.keep_in_transcript:
            if not tool.is_attached:
                self._mount_process_item(tool)
            return
        snapshot = tool.snapshot()
        group = self._tool_groups.get(tool.call_id)
        if group is not None and not (
            group is self._open_tool_group and group.rejects_last(snapshot)
        ):
            group.update_call(snapshot)
            return
        if group is not None:
            # Activity arrived with the arguments and no longer matches the
            # stretch this call joined while it was still preparing.
            group.remove_call(tool.call_id)
        group = self._tool_group_for(snapshot)
        group.add_call(snapshot)
        self._tool_groups[tool.call_id] = group

    def _tool_group_for(self, snapshot: ToolCallSnapshot) -> ToolCallSummary:
        from coding_agent.tui.tools.snapshots import ToolCallSummary

        group = self._open_tool_group
        if group is not None and group.accepts(snapshot):
            return group
        group = ToolCallSummary(expanded=True)
        self._mount_process_item(group)
        self._open_tool_group = group
        return group

    def update_tool(
        self,
        call_id: str,
        *,
        tool_name: str = "tool",
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None:
        tool = self._tools.get(call_id)
        if tool is None:
            if call_id in self._tool_groups:
                return  # a finished group row is final; its model is released
            tool = self._new_tool(call_id, tool_name)
        if status == "running":
            tool.set_running(arguments)
        elif status in {"done", "failed"}:
            tool.set_result(result)
            if status == "failed":
                tool.status = "failed"
                tool.refresh_content()
            if tool.tool_name in {"write_file", "patch", "bash"}:
                self.invalidate_workspace_caches()
        else:
            tool.set_arguments(arguments, raw_arguments)
        self._show_tool(tool)
        if not tool.keep_in_transcript and status in {"done", "failed"}:
            # The group row holds the finished call's snapshot. Dropping the
            # unmounted model keeps a session from retaining a widget tree
            # per finished call (and the GC work that comes with it).
            del self._tools[call_id]

    def append_tool_output(self, call_id: str, chunk: str) -> None:
        """Feed a streamed output chunk to its Bash card, in place."""
        from coding_agent.tui.tools.calls import BashToolWidget

        tool = self._tools.get(call_id)
        if isinstance(tool, BashToolWidget):
            tool.append_output(chunk)

    def add_notice(self, text: str, tone: str = "info") -> None:
        notice = Notice(text, tone)
        if self._busy and self._process is not None:
            self._mount_process_item(notice)
        else:
            self._mount_transcript(notice)

    def add_update(self, text: str, hint: str = "") -> None:
        overlay = self.query_one("#composer-overlay", ComposerOverlay)
        overlay.show(text, hint or "Press ctrl+q to quit the app")

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

    def finish_process(self, title: str) -> None:
        """Freeze the finished run as it stands and add its completion row."""
        self._close_tool_group()
        if self._process is not None:
            self._process.complete(title)

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
        transcript.mount(*widgets)

    def action_copy_selection(self) -> None:
        """Copy the currently selected rendered transcript text to the clipboard."""
        selected = self.screen.get_selected_text()
        if selected:
            self.copy_to_clipboard(selected)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """Copy the drag selection, then clear its highlight."""
        if self.screen.get_selected_text():
            self.action_copy_selection()
            self.notify("Copied to clipboard!")
            self.screen.clear_selection()

    def action_clear_transcript(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        transcript.remove_children()
        transcript.mount(Welcome(self.workspace))
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools.clear()
        self._tool_groups.clear()
        self._open_tool_group = None
