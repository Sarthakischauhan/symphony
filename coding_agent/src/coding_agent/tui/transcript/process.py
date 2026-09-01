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
        self._pending_items: list[Widget] = []
        self._thinking = thinking
        self._completed = False
        super().__init__(classes="run-process")

    def compose(self):  # type: ignore[no-untyped-def]
        pending, self._pending_items = self._pending_items, []
        yield self._thinking
        yield from pending

    def add_item(self, widget: Widget) -> None:
        if not self.is_attached:
            self._pending_items.append(widget)
            return
        self.mount(widget)

    def replace_item(self, old: Widget, new: Widget) -> None:
        """Swap a mounted or pending child without dropping surrounding timeline items."""
        if old in self._pending_items:
            self._pending_items[self._pending_items.index(old)] = new
            return
        if old.is_attached:
            self.mount(new, after=old)
            old.remove()

    def on_mount(self) -> None:
        self.call_after_refresh(self._flush_pending_items)

    def _flush_pending_items(self) -> None:
        if not self._pending_items:
            return
        pending, self._pending_items = self._pending_items, []
        self.mount(*pending)

    def complete(self, title: str, *, collapse: bool = True) -> None:
        del collapse
        if self._completed:
            return
        self._completed = True
        self._thinking.set_visible(False)
        self.add_item(
            Static(Text(f"✓  {title}", style="#5f6a62"), classes="process-complete")
        )


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
        self._body.update(themed_markdown(content or " ", style="#858585"))
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
        self.collapsed = True
        self.remove_class("is-live")
        self.add_class("is-complete")
