"""Folded tool and thought snapshots, and the Explored row that displays them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from rich.style import Style
from rich.text import Text
from textual import events

from coding_agent.tui.motion import settle_row
from coding_agent.tui.tools.activity import (
    choose_completion_verb,
    explored_activity,
    explored_count_label,
    explored_title,
    format_explored_duration,
    parse_activity,
    same_activity_group,
)
from coding_agent.tui.tools.labels import header_target, tool_detail, tool_label
from coding_agent.tui.transcript.messages import SelectableStatic, clip_text


@dataclass(frozen=True)
class ThoughtSnapshot:
    """Display data retained after a completed reasoning widget is folded."""

    title: str
    content: str = ""


@dataclass(frozen=True)
class ToolCallSnapshot:
    """Display data retained after a live tool card is folded away."""

    call_id: str
    tool_name: str = "tool"
    label: str = "Tool"
    detail: str = ""
    status: str = "done"
    result: str = ""
    activity_verb: str = ""
    activity_reason: str = ""
    activity_group: str = ""
    duration: float | None = None

    def as_text(self) -> str:
        marker = "×" if self.status == "failed" else "✓"
        line = f"{marker}  {self.label}"
        if self.detail:
            line = f"{line}  {self.detail}"
        if self.result:
            line = f"{line}\n   {self.result}"
        return line


def snapshot_from_call(
    *,
    call_id: str,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    raw_arguments: str = "",
    status: str = "done",
    result: str = "",
    activity: Mapping[str, Any] | None = None,
) -> ToolCallSnapshot:
    label, _icon = tool_label(tool_name)
    display_arguments = dict(arguments or {})
    nested_activity = display_arguments.pop("activity", None)
    parsed = parse_activity(activity if isinstance(activity, Mapping) else nested_activity)
    return ToolCallSnapshot(
        call_id=call_id,
        tool_name=tool_name,
        label=label,
        detail=clip_text(tool_detail(tool_name, display_arguments, raw_arguments), 300),
        status=status,
        result=clip_text(result, 260) if result else "",
        activity_verb=parsed.verb,
        activity_reason=parsed.reason,
        activity_group=parsed.group,
        duration=None,
    )


NESTED_GUIDE = "tool-call-summary--guide"
NESTED_VERB = "tool-call-summary--verb"
NESTED_ARGS = "tool-call-summary--args"
NESTED_DETAIL = "tool-call-summary--detail"
GLYPH_DONE = "tool-call-summary--glyph-done"
GLYPH_RUNNING = "tool-call-summary--glyph-running"
GLYPH_FAILED = "tool-call-summary--glyph-failed"
# fx (vercel-labs/fx) draws a tree guide in front of grouped tool rows:
# "├" for every row but the last, "└" for the last, and "│" under a
# non-final row when it continues onto a second line.
GUIDE_BRANCH = "├"
GUIDE_LAST = "└"
GUIDE_CONTINUE = "│"
GUIDE_END = " "
# fx marks completed and failed calls with "●" and colours failures red;
# calls that have not finished keep the hollow marker the live rows use.
FINISHED_GLYPH = "●"
PENDING_GLYPH = "○"
ROW_GLYPHS: Mapping[str, tuple[str, str]] = {
    "done": (FINISHED_GLYPH, GLYPH_DONE),
    "failed": (FINISHED_GLYPH, GLYPH_FAILED),
}
PENDING_ROW_GLYPH = (PENDING_GLYPH, GLYPH_RUNNING)
# Used before the widget is mounted (no stylesheet yet); TCSS supplies the
# themed colours once it is.
UNMOUNTED_NESTED_STYLE = Style()
# Nested rows stay regular weight while the focused/hovered header is bold.
NESTED_WEIGHT = Style(bold=False)


def row_glyph(status: str) -> tuple[str, str]:
    """Return the status glyph and its component class for one nested row."""
    return ROW_GLYPHS.get(status, PENDING_ROW_GLYPH)


def detail_preview(content: str, limit: int) -> str:
    """Collapse whitespace so a thought preview fits on one line."""
    return clip_text(" ".join(content.split()), limit)


def guide_glyphs(is_last: bool) -> tuple[str, str]:
    """Return the guide for a row's first line and for its continuation."""
    if is_last:
        return GUIDE_LAST, GUIDE_END
    return GUIDE_BRANCH, GUIDE_CONTINUE


class ToolCallSummary(SelectableStatic, can_focus=True):
    """A compact disclosure containing non-interactive tool snapshots.

    Expanded rows start at the header's left edge behind an fx-style tree
    guide, one line each: guide, status glyph, verb, then arguments. The
    ``tool-call-summary--*`` component classes in theme.toml colour each part.
    """

    COMPONENT_CLASSES = {
        NESTED_GUIDE,
        NESTED_VERB,
        NESTED_ARGS,
        NESTED_DETAIL,
        GLYPH_DONE,
        GLYPH_RUNNING,
        GLYPH_FAILED,
    }

    def __init__(
        self, calls: Sequence[ToolCallSnapshot | ThoughtSnapshot] | None = None
    ) -> None:
        self.calls: list[ToolCallSnapshot] = []
        self.entries: list[ToolCallSnapshot | ThoughtSnapshot] = []
        self.is_expanded = False
        super().__init__(classes="tool-call-summary", markup=False)
        for call in calls or ():
            if isinstance(call, ThoughtSnapshot):
                self.add_thought(call.title, call.content, layout=False)
            else:
                self.add_call(call, layout=False)
        self.title = self._summary_title()

    def on_mount(self) -> None:
        settle_row(self)

    def _thought_count(self) -> int:
        return sum(isinstance(entry, ThoughtSnapshot) for entry in self.entries)

    def _summary_title(self) -> str:
        return explored_title(self.calls, thought_count=self._thought_count())

    def accepts(self, call: object) -> bool:
        """Return whether a call belongs in this activity's folded row."""
        from coding_agent.tui.tools.calls import ToolCallWidget

        if not self.calls:
            return True
        snapshot = call.snapshot() if isinstance(call, ToolCallWidget) else call
        return same_activity_group(explored_activity(self.calls), snapshot)

    def render(self) -> Text:
        activity = explored_activity(self.calls)
        heading = activity.verb or activity.reason or "Explored"
        text = Text()
        text.append(clip_text(heading, 96), style="bold #8ab4cf")
        duration = format_explored_duration(self.calls)
        timing = f" for {duration}" if duration else ""
        count = explored_count_label(
            tool_count=self.count, thought_count=self._thought_count()
        )
        text.append(f" · {count}{timing}", style="#a2adb8")
        failed = sum(call.status == "failed" for call in self.calls)
        if failed:
            text.append(f" · {failed} failed", style="bold #d66b73")
        if not self.is_expanded:
            thought = next(
                (entry for entry in self.entries if isinstance(entry, ThoughtSnapshot)),
                None,
            )
            if thought is not None and thought.content:
                self._append_detail(text, thought.content, 96)
            return text
        self._append_nested_rows(text)
        return text

    def _nested_style(self, component: str) -> Style:
        themed = self.get_component_rich_style(
            component, partial=True, default=UNMOUNTED_NESTED_STYLE
        )
        return themed + NESTED_WEIGHT

    def _append_detail(self, text: Text, content: str, limit: int) -> None:
        text.append(f"\n{detail_preview(content, limit)}", style=self._nested_style(NESTED_DETAIL))

    def _append_nested_rows(self, text: Text) -> None:
        """One compact line per entry behind the guide, flush with the header."""
        last_index = len(self.entries) - 1
        for index, entry in enumerate(self.entries):
            guide, continuation = guide_glyphs(index == last_index)
            if isinstance(entry, ThoughtSnapshot):
                self._append_row(text, guide, "done", entry.title, "")
                if entry.content:
                    self._append_continuation(text, continuation, entry.content)
                continue
            self._append_row(text, guide, entry.status, entry.label, header_target(entry.detail))

    def _append_row(self, text: Text, guide: str, status: str, verb: str, args: str) -> None:
        glyph, glyph_component = row_glyph(status)
        text.append("\n")
        text.append(guide, style=self._nested_style(NESTED_GUIDE))
        text.append(" ")
        text.append(glyph, style=self._nested_style(glyph_component))
        text.append(" ")
        text.append(verb, style=self._nested_style(NESTED_VERB))
        if args:
            text.append(f" {args}", style=self._nested_style(NESTED_ARGS))

    def _append_continuation(self, text: Text, guide: str, content: str) -> None:
        text.append("\n")
        text.append(guide, style=self._nested_style(NESTED_GUIDE))
        text.append(f" {detail_preview(content, 220)}", style=self._nested_style(NESTED_DETAIL))

    @property
    def call_ids(self) -> list[str]:
        return [call.call_id for call in self.calls]

    @property
    def count(self) -> int:
        return len(self.calls)

    def add_call(self, call: object, *, layout: bool = True) -> None:
        from coding_agent.tui.tools.calls import ToolCallWidget

        if isinstance(call, ToolCallWidget):
            snapshot = call.snapshot()
        elif isinstance(call, ToolCallSnapshot):
            snapshot = call
        else:
            snapshot = ToolCallSnapshot(call_id=str(call))
        if snapshot.call_id not in self.call_ids:
            self.calls.append(snapshot)
            self.entries.append(snapshot)
        from textual._context import NoActiveAppError

        try:
            self.title = self._summary_title()
            self.set_class(any(item.status == "failed" for item in self.calls), "has-failures")
            if layout:
                self.refresh(layout=True)
        except NoActiveAppError:
            pass

    def add_thought(
        self,
        title: str,
        content: str = "",
        *,
        layout: bool = True,
    ) -> None:
        self.entries.append(ThoughtSnapshot(title=title, content=content))
        self.title = self._summary_title()
        if layout:
            self.refresh(layout=True)

    def toggle(self) -> None:
        self.is_expanded = not self.is_expanded
        self.refresh(layout=True)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.toggle()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            event.prevent_default()
            self.toggle()

    def snapshot_text(self) -> str:
        return "\n\n".join(call.as_text() for call in self.calls)

    def archive_text(self) -> str:
        """Keep archived/explore transcripts as compact tool names only."""
        return "\n".join(
            entry.title if isinstance(entry, ThoughtSnapshot) else entry.label
            for entry in self.entries
        )


class CompletedRunSummary(ToolCallSummary):
    """A folded collection covering the work that happened before the final reply."""

    def __init__(
        self,
        calls: Sequence[ToolCallSnapshot] | None = None,
        *,
        verb: str = "",
        duration: str = "",
        detail: str = "",
    ) -> None:
        self._verb = verb.strip() or choose_completion_verb()
        self._duration = duration
        self._detail = detail
        super().__init__(calls)

    def _summary_title(self) -> str:
        timing = f" for {self._duration}" if self._duration else ""
        detail = f" · {self._detail}" if self._detail else ""
        return f"{self._verb}{timing}{detail}"

    def render(self) -> Text:
        text = Text()
        text.append(self._verb, style="bold #8ab4cf")
        if self._duration:
            text.append(f" for {self._duration}", style="#a2adb8")
        if self._detail:
            text.append(f" · {self._detail}", style="#a2adb8")
        if self.is_expanded:
            self._append_nested_rows(text)
        return text
