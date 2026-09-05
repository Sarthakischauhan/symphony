"""Live run-process widgets: thinking, timeline, and reasoning."""

from __future__ import annotations

import re
from typing import Any

from rich.text import Text
from textual.containers import Container, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from coding_agent.tui.theme import themed_markdown


class ThinkingStatus(Static):
    """Muted run/usage metadata displayed directly beneath the user prompt."""

    _WORKING_COLORS = (
        "#6f5930",
        "#94733a",
        "#bd9145",
        "#e2b85f",
        "#f0d58a",
        "#d7a84b",
        "#a77f3d",
    )

    def __init__(self, text: str = "Thinking…") -> None:
        self._working = False
        self._working_detail = ""
        self._gradient_step = 0
        self._animation_timer: Any = None
        super().__init__(classes="thinking-status")
        self.set_text(text)

    def on_mount(self) -> None:
        self._animation_timer = self.set_interval(0.12, self._advance_gradient)
        self._sync_animation_timer()

    def on_unmount(self) -> None:
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

    def watch_display(self, display: bool) -> None:
        del display
        self._sync_animation_timer()

    def set_visible(self, visible: bool) -> None:
        """Show or hide the status line and pause the gradient when it is off-screen."""
        self.display = visible
        self._sync_animation_timer()

    def _sync_animation_timer(self) -> None:
        timer = self._animation_timer
        if timer is None:
            return
        if self._working and self.display:
            timer.resume()
        else:
            timer.pause()

    def set_text(self, value: str) -> None:
        self._working = False
        self._sync_animation_timer()
        self.update(Text(f"✻  {value}", style="#666666"))

    def set_working(self, detail: str = "") -> None:
        """Show a moving color gradient while a model request is retrying."""
        self._working = True
        self._working_detail = detail
        self._sync_animation_timer()
        self._render_working()

    def _advance_gradient(self) -> None:
        if not self._working or not self.display:
            self._sync_animation_timer()
            return
        self._gradient_step = (self._gradient_step + 1) % len(self._WORKING_COLORS)
        self._render_working()

    def _render_working(self) -> None:
        label = "✻  Working"
        line = Text()
        for index, character in enumerate(label):
            color = self._WORKING_COLORS[
                (index + self._gradient_step) % len(self._WORKING_COLORS)
            ]
            line.append(character, style=f"bold {color}")
        if self._working_detail:
            line.append(f"  ·  {self._working_detail}", style="#666666")
        self.update(line)


class RunProcess(Container):
    """One run's flat timeline of live status, thoughts, and tools."""

    def __init__(self, thinking: ThinkingStatus) -> None:
        # ``_items`` is the single source of truth for timeline order. Items
        # added before this container is composed are yielded by ``compose``;
        # items added afterwards are mounted directly.
        self._items: list[Widget] = [thinking]
        self._thinking = thinking
        self._completed = False
        self.archiveable = True
        super().__init__(classes="run-process")

    def compose(self):  # type: ignore[no-untyped-def]
        yield from self._items

    def add_item(self, widget: Widget) -> None:
        self._items.append(widget)
        if self.is_mounted:
            self.mount(widget)

    def timeline_items(self) -> list[Widget]:
        """Timeline order, including items not yet flushed to the DOM."""
        return list(self._items)

    def replace_item(self, old: Widget, new: Widget) -> None:
        """Swap a mounted or pending child without dropping surrounding timeline items."""

        try:
            index = self._items.index(old)
        except ValueError:
            return
        self._items[index] = new
        if old.is_attached:
            self.mount(new, after=old)
            old.remove()

    def remove_item(self, widget: Widget) -> None:
        if widget in self._items:
            self._items.remove(widget)
        if widget.is_attached:
            widget.remove()

    def on_mount(self) -> None:
        # Anything added after compose ran but before Mount was handled has
        # not reached the DOM yet; mount it now in timeline order.
        pending = [item for item in self._items if item.parent is None]
        if pending:
            self.mount(*pending)

    @property
    def completed(self) -> bool:
        return self._completed

    def complete(self, title: str, *, collapse: bool = True) -> None:
        if self._completed:
            return
        self._completed = True
        self.archiveable = collapse
        self._thinking.set_visible(False)
        self.add_item(
            Static(Text(f"✓  {title}", style="#5f6a62"), classes="process-complete")
        )

    def tool_count(self) -> int:
        from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget

        count = 0
        for item in self.timeline_items():
            if isinstance(item, ToolCallWidget):
                count += 1
            elif isinstance(item, ToolCallSummary):
                count += item.count
        return count

    def archive_text(self) -> str:
        from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget

        chunks: list[str] = []
        for item in self.timeline_items():
            if isinstance(item, ThinkingStatus):
                continue
            if isinstance(item, ReasoningWidget):
                if item.reasoning_text:
                    chunks.append(f"THOUGHT\n{item.reasoning_text}")
            elif isinstance(item, ToolCallWidget):
                chunks.append(item.snapshot().as_text())
            elif isinstance(item, ToolCallSummary):
                chunks.append(item.archive_text())
            else:
                archive = getattr(item, "archive_text", None)
                if callable(archive):
                    chunks.append(str(archive()))
        return "\n\n".join(chunk for chunk in chunks if chunk)


class ReasoningWidget(Collapsible):
    """A live tail-following thought that folds into the tool timeline."""

    def __init__(self, content: str = "") -> None:
        self._summary_heading: str | None = None
        self._content_without_heading = content
        self._body = Static(classes="reasoning-text")
        self._scroll = VerticalScroll(self._body, classes="reasoning-scroll")
        super().__init__(
            self._scroll,
            title="Thinking…",
            collapsed=False,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            classes="reasoning-block is-live",
        )
        self.set_content(content)

    def set_content(self, content: str) -> None:
        self.reasoning_text = content
        self._summary_heading, self._content_without_heading = (
            self._extract_summary_heading(content)
        )
        # Rich Markdown parsing is deferred until completion. During a stream,
        # plain text is both cheaper and resilient to incomplete markup.
        self._body.update(content or " ")
        if self.is_mounted:
            self._scroll.scroll_end(animate=False, force=True)

    @staticmethod
    def _extract_summary_heading(content: str) -> tuple[str | None, str]:
        """Return a standalone leading Markdown heading and the remaining body."""
        match = re.match(
            r"\A[ \t]*(?:"
            r"#{1,6}[ \t]+(?P<atx>[^\n]+?)[ \t]*#*"
            r"|\*\*(?P<bold>[^\n]+?)\*\*"
            r"|__(?P<underscore>[^\n]+?)__"
            r")[ \t]*(?:\n[ \t]*\n|\Z)",
            content,
        )
        if match is None:
            return None, content
        heading = next(value for value in match.groupdict().values() if value)
        return heading.strip(), content[match.end() :]

    def on_mount(self) -> None:
        self._scroll.anchor()

    def complete(self) -> None:
        if self.is_mounted:
            self._scroll.anchor(False)
            self._scroll.scroll_home(animate=False, force=True)
        if self._summary_heading:
            self.title = f"Thought - {self._summary_heading}"
            self._body.update(
                themed_markdown(self._content_without_heading or " ", style="#858585")
            )
        else:
            self.title = "Thought"
            self._body.update(themed_markdown(self.reasoning_text or " ", style="#858585"))
        self.collapsed = True
        self.remove_class("is-live")
        self.add_class("is-complete")
