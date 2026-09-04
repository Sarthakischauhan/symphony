"""Bounded transcript containers and lazy archive summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import events
from textual.widget import Widget
from textual.widgets import Static

from coding_agent.tui.screens.modal import ContentModal


@dataclass(frozen=True)
class TurnSnapshot:
    """Plain display data retained after a completed turn leaves the DOM."""

    text: str
    tool_count: int


class TranscriptTurn:
    """Track one turn's root widgets without changing their display order."""

    def __init__(self, first: Widget) -> None:
        self._items = [first]
        self.completed = False

    def add_item(self, widget: Widget) -> None:
        self._items.append(widget)

    def timeline_items(self) -> list[Widget]:
        return list(self._items)

    def replace_item(self, old: Widget, new: Widget) -> None:
        try:
            index = self._items.index(old)
        except ValueError:
            return
        self._items[index] = new
        if old.is_attached:
            old.parent.mount(new, after=old)
            old.remove()

    def remove_item(self, widget: Widget) -> None:
        if widget in self._items:
            self._items.remove(widget)
        if widget.is_attached:
            widget.remove()

    def tool_count(self) -> int:
        from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget
        from coding_agent.tui.transcript.process import RunProcess

        count = 0
        for item in self._items:
            if isinstance(item, ToolCallWidget):
                count += 1
            elif isinstance(item, ToolCallSummary):
                count += item.count
            elif isinstance(item, RunProcess):
                count += item.tool_count()
        return count

    def snapshot(self) -> TurnSnapshot:
        chunks = [text for item in self._items if (text := _archive_text(item))]
        return TurnSnapshot("\n\n".join(chunks), self.tool_count())


class TranscriptArchive(Static, can_focus=True):
    """One live row for completed transcript turns, with details opened lazily."""

    def __init__(self) -> None:
        self._turns: list[TurnSnapshot] = []
        super().__init__(self._line(), classes="transcript-archive")

    @property
    def tool_count(self) -> int:
        return sum(turn.tool_count for turn in self._turns)

    def add_turn(self, snapshot: TurnSnapshot) -> None:
        self._turns.append(snapshot)
        self.update(self._line(), layout=False)

    def _line(self) -> Text:
        turns = len(self._turns)
        turn_label = "turn" if turns == 1 else "turns"
        tool_label = "tool" if self.tool_count == 1 else "tools"
        line = Text("[ ", style="#666666")
        line.append("Archived", style="#d7a84b")
        line.append(
            f"       {turns} {turn_label} · {self.tool_count} {tool_label}]",
            style="#666666",
        )
        return line

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.open_archive()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.open_archive()

    def open_archive(self) -> None:
        content = "\n\n".join(turn.text for turn in self._turns if turn.text)
        self.app.push_screen(ContentModal(content or "No archived transcript content."))


def _archive_text(widget: Any) -> str:
    archive = getattr(widget, "archive_text", None)
    if callable(archive):
        return str(archive()).strip()
    return ""
