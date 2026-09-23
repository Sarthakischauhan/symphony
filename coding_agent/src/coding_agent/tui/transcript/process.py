"""Live run-process widgets: thinking, timeline, and reasoning."""

from __future__ import annotations

import random
import re
import time
from time import monotonic
from typing import Any

from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from coding_agent.tui.motion import enter_row, reveal, settle_row
from coding_agent.tui.transcript.messages import SelectableStatic


class ThinkingStatus(Static):
    """Muted run/usage metadata displayed directly beneath the user prompt."""

    # Short, present-participle activity verbs in the style of Claude Code's
    # spinner words. These rotate while a model turn is in flight.
    _CHURNING_VERBS = (
        "Thinking",
        "Cooking",
        "Noodling",
        "Pondering",
        "Wandering",
        "Tinkering",
        "Musing",
        "Orbiting",
        "Whisking",
        "Grooving",
        "Spelunking",
        "Percolating",
        "Ruminating",
        "Concocting",
        "Meandering",
        "Incubating",
        "Harmonizing",
        "Forging",
        "Sketching",
        "Vibing",
        "Stargazing",
        "Brewing",
        "Marinating",
        "Gallivanting",
        "Pontificating",
        "Combobulating",
        "Enchanting",
        "Moonwalking",
        "Reticulating",
        "Wrangling",
    )

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
        self._churning = False
        self._working_detail = ""
        self._gradient_step = 0
        self._churning_started_at = 0.0
        self._churning_verb = "Thinking"
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
        self._churning = False
        self._working = False
        self._sync_animation_timer()
        self.styles.opacity = 1.0
        self.update(Text(f"✻  {value}", style="#666666"))

    def set_churning(self, turn: int) -> None:
        """Show the normal waiting state for a model turn."""
        self._churning = True
        self._working = True
        self._working_detail = ""
        self._churning_started_at = time.monotonic()
        self._churning_verb = random.choice(self._CHURNING_VERBS)
        self._sync_animation_timer()
        self._render_churning()

    def _render_churning(self) -> None:
        # Elapsed text only. Opacity pulses here fight transcript enter/settle
        # and stack a new animation on every timer tick.
        elapsed = time.monotonic() - self._churning_started_at
        self.update(Text(f"{self._churning_verb} {elapsed:.1f}s", style="#858585"))
        self.styles.opacity = 1.0

    def set_working(self, detail: str = "") -> None:
        """Show a moving color gradient while a model request is retrying."""
        self._churning = False
        self._working = True
        self._working_detail = detail
        self._sync_animation_timer()
        self._render_working()

    def _advance_gradient(self) -> None:
        if not self._working or not self.display:
            self._sync_animation_timer()
            return
        if self._churning:
            self._render_churning()
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

    def on_mount(self) -> None:
        """Reveal the run and mount items queued during composition."""
        reveal(self, duration=0.22)
        pending = [item for item in self._items if item.parent is None]
        if pending:
            self.mount(*pending)

    def add_item(self, widget: Widget) -> None:
        self._items.append(widget)
        if self.is_mounted:
            self.mount(widget)

    def place_thinking_last(self) -> None:
        """Keep the live status below the work it is describing."""
        if self._items and self._items[-1] is self._thinking:
            return
        if not self._thinking.is_attached:
            if self._thinking in self._items:
                self._items.remove(self._thinking)
            self._items.append(self._thinking)
            return
        try:
            self._items.remove(self._thinking)
        except ValueError:
            return
        self._items.append(self._thinking)
        self._thinking.remove()
        self.mount(self._thinking)

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

    @property
    def completed(self) -> bool:
        return self._completed

    def complete(
        self,
        title: str,
        *,
        collapse: bool = True,
        add_completion: bool = True,
        verb: str = "",
        duration: str = "",
        detail: str = "",
    ) -> None:
        if self._completed:
            return
        self._completed = True
        self.archiveable = collapse
        self._thinking.set_visible(False)
        if collapse:
            self.fold_into_summary(verb=verb, duration=duration, detail=detail)
            # Keep the canonical metrics line visible as its own row. The
            # folded timeline is a tool/thought disclosure and must not replace
            # the process summary.
            self.add_item(ProcessComplete(title))
        elif add_completion:
            self.add_item(ProcessComplete(title))

    def fold_into_summary(
        self, *, verb: str = "", duration: str = "", detail: str = ""
    ) -> None:
        """Replace remaining live timeline cards with a completed-run fold."""
        from coding_agent.tui.tools.calls import ToolCallWidget
        from coding_agent.tui.tools.snapshots import CompletedRunSummary
        from coding_agent.tui.transcript.messages import AssistantMessage

        summary = CompletedRunSummary(
            verb=verb,
            duration=duration,
            detail=detail,
        )
        assistants: list[AssistantMessage] = []
        for item in list(self.timeline_items()):
            if item is self._thinking:
                self.remove_item(item)
                continue
            if isinstance(item, AssistantMessage):
                assistants.append(item)
                continue
            if isinstance(item, ReasoningWidget):
                summary.add_thought(item.title, item.reasoning_text, layout=False)
                self.remove_item(item)
                continue
            if isinstance(item, ToolCallWidget):
                if getattr(item, "keep_in_transcript", False) or item.tool_name in {
                    "generate_image",
                    "spawn_agent",
                }:
                    continue
                summary.add_call(item, layout=False)
                self.remove_item(item)
                continue
            from coding_agent.tui.tools.snapshots import ThoughtSnapshot, ToolCallSummary

            if isinstance(item, ToolCallSummary):
                for entry in item.entries:
                    if isinstance(entry, ThoughtSnapshot):
                        summary.add_thought(entry.title, entry.content, layout=False)
                    else:
                        summary.add_call(entry, layout=False)
                self.remove_item(item)
        final_assistant = assistants[-1] if assistants else None
        for assistant in assistants[:-1]:
            self.remove_item(assistant)
        if final_assistant is not None and final_assistant in self._items:
            index = self._items.index(final_assistant)
            self._items.insert(index, summary)
            if final_assistant.is_attached:
                self.mount(summary, before=final_assistant)
            return
        self.add_item(summary)

    def tool_count(self) -> int:
        from coding_agent.tui.tools.calls import ToolCallWidget
        from coding_agent.tui.tools.snapshots import ToolCallSummary

        count = 0
        for item in self.timeline_items():
            if isinstance(item, ToolCallWidget):
                count += 1
            elif isinstance(item, ToolCallSummary):
                count += item.count
        return count

    def archive_text(self) -> str:
        from coding_agent.tui.tools.calls import ToolCallWidget
        from coding_agent.tui.tools.snapshots import ToolCallSummary

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


class ProcessComplete(Static):
    """Compact completion row with a restrained reveal."""

    def __init__(self, title: str) -> None:
        super().__init__(
            Text(f"✓  {title}", style="#858585"), classes="process-complete"
        )

    def on_mount(self) -> None:
        reveal(self, duration=0.16)


class ReasoningHeader(Horizontal, can_focus=True):
    """Focusable Thought header that matches the compact tool-call line."""

    class Toggle(Message):
        pass

    def _on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Toggle())

    def _on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.post_message(self.Toggle())


class ReasoningWidget(Collapsible):
    """A live tail-following thought that folds into the tool timeline."""

    def __init__(self, content: str = "") -> None:
        self._summary_heading: str | None = None
        self._content_without_heading = content
        self._body = SelectableStatic(classes="reasoning-text")
        self._scroll = VerticalScroll(self._body, classes="reasoning-scroll")
        self._label = Static("Thinking…", classes="reasoning-label", markup=False)
        self._status = Static("", classes="reasoning-status", markup=False)
        self._started_at = monotonic()
        self._duration: float | None = None
        super().__init__(
            self._scroll,
            title="Thinking…",
            collapsed=False,
            collapsed_symbol="",
            expanded_symbol="",
            classes="reasoning-block is-live",
        )
        self.set_content(content)

    def compose(self):  # type: ignore[no-untyped-def]
        # Keep CollapsibleTitle in the DOM for keyboard/accessibility compatibility;
        # the visible header matches the compact tool-call line.
        yield self._title
        with ReasoningHeader(classes="reasoning-header"):
            yield self._label
            yield self._status
        with self.Contents():
            yield self._scroll

    def on_reasoning_header_toggle(self, event: ReasoningHeader.Toggle) -> None:
        event.stop()
        self.collapsed = not self.collapsed

    def _watch_collapsed(self, collapsed: bool) -> None:
        self._update_collapsed(collapsed)
        if collapsed:
            self.post_message(self.Collapsed(self))
        else:
            self.post_message(self.Expanded(self))
        self._scroll.display = not collapsed

    def _set_visible_title(self, title: str) -> None:
        self.title = title
        label, _, duration = title.partition(" ")
        self._label.update(label or "Thought")
        self._status.update(duration)

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
        enter_row(self, duration=0.14)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 10:
            return f"{seconds:.1f}s"
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes}m {remainder:02d}s"

    def complete(self) -> None:
        if self.has_class("is-complete"):
            return
        if self.is_mounted:
            self._scroll.anchor(False)
            self._scroll.scroll_home(animate=False, force=True)
        self._duration = max(0.0, monotonic() - self._started_at)
        completed_title = f"Thought {self._format_duration(self._duration)}"
        body = self.reasoning_text.strip() or " "
        self._body.update(body)
        # Keep completed reasoning expanded so the provider's streamed content
        # remains visible; the title still identifies the Thought row.
        self.collapsed = False
        self._set_visible_title(completed_title)
        self.remove_class("is-live")
        self.add_class("is-complete")
        settle_row(self)
