"""Conversation-turn tracking for transcript tool condensation."""

from __future__ import annotations

from textual.widget import Widget


class TranscriptTurn:
    """Track one turn's root widgets without changing their display order."""

    def __init__(self, first: Widget) -> None:
        self._items = [first]

    def add_item(self, widget: Widget) -> None:
        self._items.append(widget)

    def insert_item(
        self,
        widget: Widget,
        *,
        before: Widget | None = None,
        after: Widget | None = None,
    ) -> None:
        """Insert a root widget while preserving surrounding turn order."""
        if before is not None and before in self._items:
            self._items.insert(self._items.index(before), widget)
            return
        if after is not None and after in self._items:
            self._items.insert(self._items.index(after) + 1, widget)
            return
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
        from coding_agent.tui.tools.calls import ToolCallWidget
        from coding_agent.tui.tools.snapshots import ToolCallSummary
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
