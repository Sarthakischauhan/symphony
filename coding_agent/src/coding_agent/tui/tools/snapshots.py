"""Tool and thought snapshots, and the Explored group row that displays them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from rich.style import Style
from rich.text import Text
from textual import events

from coding_agent.tui.tools.activity import (
    choose_completion_verb,
    explored_activity,
    explored_count_label,
    explored_title,
    format_explored_duration,
    parse_activity,
    same_activity_group,
)
from coding_agent.tui.tools.labels import header_target, patch_path, tool_detail, tool_label
from coding_agent.tui.transcript.messages import (
    SelectableStatic,
    clip_text,
    return_composer_focus,
)
from coding_agent.tui.transcript.thinking_markdown import thinking_plain_text


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
    detail = tool_detail(tool_name, display_arguments, raw_arguments)
    if tool_name == "patch" and not detail:
        detail = patch_path(display_arguments, raw_arguments, result)
    return ToolCallSnapshot(
        call_id=call_id,
        tool_name=tool_name,
        label=label,
        detail=clip_text(detail, 300),
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
NESTED_VERB_FAILED = "tool-call-summary--verb-failed"
NESTED_VERB_RUNNING = "tool-call-summary--verb-running"
LIVE_STATUSES = frozenset({"preparing", "running"})
# fx (vercel-labs/fx) draws a tree guide in front of grouped tool rows:
# "├" for every row but the last, "└" for the last, and "│" under a
# non-final row when it continues onto a second line.
GUIDE_BRANCH = "├"
GUIDE_LAST = "└"
GUIDE_CONTINUE = "│"
GUIDE_END = " "
# Used before the widget is mounted (no stylesheet yet); TCSS supplies the
# themed colours once it is.
UNMOUNTED_NESTED_STYLE = Style()
# Nested rows stay regular weight while the focused/hovered header is bold.
NESTED_WEIGHT = Style(bold=False)


def verb_component(status: str) -> str:
    """Return the verb's component class: danger when failed, warning while live."""
    if status == "failed":
        return NESTED_VERB_FAILED
    if status in LIVE_STATUSES:
        return NESTED_VERB_RUNNING
    return NESTED_VERB


def detail_preview(content: str, limit: int) -> str:
    """A thought's markdown as one clipped line of plain text, markers stripped."""
    return clip_text(thinking_plain_text(content), limit)


def guide_glyphs(is_last: bool) -> tuple[str, str]:
    """Return the guide for a row's first line and for its continuation."""
    if is_last:
        return GUIDE_LAST, GUIDE_END
    return GUIDE_BRANCH, GUIDE_CONTINUE


def append_nested_row(
    text: Text, styles: Mapping[str, Style], guide: str, status: str, verb: str, args: str
) -> None:
    """Append one row: guide, verb (coloured by status), then arguments."""
    text.append("\n")
    text.append(guide, style=styles[NESTED_GUIDE])
    text.append(" ")
    text.append(verb, style=styles[verb_component(status)])
    if args:
        text.append(f" {args}", style=styles[NESTED_ARGS])


def append_continuation(text: Text, styles: Mapping[str, Style], guide: str, content: str) -> None:
    """Append a row's second line under the guide's continuation glyph."""
    text.append("\n")
    text.append(guide, style=styles[NESTED_GUIDE])
    text.append(f" {detail_preview(content, 220)}", style=styles[NESTED_DETAIL])


class ToolCallSummary(SelectableStatic, can_focus=True):
    """One stretch of non-interactive tool calls, grouped at render time.

    The live transcript mounts a group once and updates its rows in place:
    ``update_call`` swaps a call's snapshot, so running → done is a text
    change. A live group starts expanded; ``close`` folds it when the stretch
    ends unless the reader opened it themselves.

    Expanded rows start at the header's left edge behind an fx-style tree
    guide, one line each: guide, verb, then arguments. The
    ``tool-call-summary--*`` component classes in theme.toml colour each part.
    """

    COMPONENT_CLASSES = {
        NESTED_GUIDE,
        NESTED_VERB,
        NESTED_ARGS,
        NESTED_DETAIL,
        NESTED_VERB_FAILED,
        NESTED_VERB_RUNNING,
    }

    def __init__(
        self,
        calls: Sequence[ToolCallSnapshot | ThoughtSnapshot] | None = None,
        *,
        expanded: bool = False,
    ) -> None:
        self.calls: list[ToolCallSnapshot] = []
        self.entries: list[ToolCallSnapshot | ThoughtSnapshot] = []
        self.is_expanded = expanded
        # Set when the reader toggles the group; ``close`` never folds it then.
        self.user_expanded = False
        super().__init__(classes="tool-call-summary", markup=False)
        for call in calls or ():
            if isinstance(call, ThoughtSnapshot):
                self.add_thought(call.title, call.content, layout=False)
            else:
                self.add_call(call, layout=False)
        self.title = self._summary_title()

    def _thought_count(self) -> int:
        return sum(isinstance(entry, ThoughtSnapshot) for entry in self.entries)

    def _summary_title(self) -> str:
        return explored_title(self.calls, thought_count=self._thought_count())

    def accepts(self, snapshot: ToolCallSnapshot) -> bool:
        """Return whether a call belongs in this activity's group."""
        if not self.calls:
            return True
        return same_activity_group(explored_activity(self.calls), snapshot)

    def rejects_last(self, snapshot: ToolCallSnapshot) -> bool:
        """Whether this group's newest call no longer matches the calls before it."""
        if len(self.calls) < 2 or self.calls[-1].call_id != snapshot.call_id:
            return False
        return not same_activity_group(explored_activity(self.calls[:-1]), snapshot)

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
        styles = {component: self._nested_style(component) for component in self.COMPONENT_CLASSES}
        last_index = len(self.entries) - 1
        for index, entry in enumerate(self.entries):
            guide, continuation = guide_glyphs(index == last_index)
            if isinstance(entry, ThoughtSnapshot):
                title = thinking_plain_text(entry.title)
                append_nested_row(text, styles, guide, "done", title, "")
                if entry.content:
                    append_continuation(text, styles, continuation, entry.content)
                continue
            append_nested_row(
                text, styles, guide, entry.status, entry.label, header_target(entry.detail)
            )

    @property
    def call_ids(self) -> list[str]:
        return [call.call_id for call in self.calls]

    @property
    def count(self) -> int:
        return len(self.calls)

    def add_call(self, snapshot: ToolCallSnapshot, *, layout: bool = True) -> None:
        if snapshot.call_id not in self.call_ids:
            self.calls.append(snapshot)
            self.entries.append(snapshot)
        self.title = self._summary_title()
        self.set_class(any(item.status == "failed" for item in self.calls), "has-failures")
        if layout and self.is_mounted:
            self.refresh(layout=True)

    def update_call(self, snapshot: ToolCallSnapshot) -> None:
        """Swap in a call's newer snapshot; a status change only re-renders text."""
        index = self.call_ids.index(snapshot.call_id)
        previous = self.calls[index]
        self.calls[index] = snapshot
        self.entries[self.entries.index(previous)] = snapshot
        self.title = self._summary_title()
        self.set_class(any(item.status == "failed" for item in self.calls), "has-failures")
        reshaped = (previous.label, previous.detail) != (snapshot.label, snapshot.detail) or (
            previous.status == "failed"
        ) != (snapshot.status == "failed")
        self.refresh(layout=reshaped)

    def remove_call(self, call_id: str) -> None:
        index = self.call_ids.index(call_id)
        self.entries.remove(self.calls.pop(index))
        self.title = self._summary_title()
        self.refresh(layout=True)

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
        """The reader's expand/collapse; a group they opened stays open."""
        self.is_expanded = not self.is_expanded
        self.user_expanded = self.is_expanded
        self.refresh(layout=True)

    def close(self) -> None:
        """Fold a finished live stretch unless the reader opened it."""
        if self.is_expanded and not self.user_expanded:
            self.is_expanded = False
            self.refresh(layout=True)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.toggle()
        self.app.call_after_refresh(return_composer_focus, self)

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
