"""Conversation transcript widgets for the coding-agent TUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.containers import Container, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from coding_agent.tui.screens.modal import ContentModal
from coding_agent.tui.theme import themed_markdown
from coding_agent.tui.tools.images import IMAGE_MARKER_RE, ImageAttachment, ImageModal


def compact_json(value: Mapping[str, Any]) -> str:
    """Serialize a mapping compactly for single-line UI summaries."""
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def clip_text(value: Any, limit: int = 420) -> str:
    """Trim text to a display limit while preserving a visual ellipsis."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def preview_text(value: Any, limit: int = 180) -> str:
    """Trim an event value for a short notice message."""
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"

class TopBar(Static):
    """Terminal header with a quiet workspace label and model label."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._workspace = ""
        self._model = ""
        super().__init__(*args, **kwargs)

    def compose(self):  # type: ignore[no-untyped-def]
        yield Static("◆  symphony", id="topbar-product")
        yield Static(id="topbar-workspace")
        yield Static(id="topbar-model")

    def set_context(self, workspace: Path, model: str = "") -> None:
        self._workspace = str(workspace)
        self._model = model
        self.query_one("#topbar-workspace", Static).update(
            Text(self._workspace, style="#777777")
        )
        self.query_one("#topbar-model", Static).update(
            Text(f" {model or 'no model'} ", style="#a0a0a0")
        )


class Welcome(Static):
    def __init__(self, workspace: Path) -> None:
        body = Group(
            Text("Symphony", style="bold #f0f0f0"),
            Text("Coding agent", style="#858585"),
            Text(""),
            Text(f"  {workspace}", style="#666666"),
            Text(""),
            Text("Describe a task, ask a question, or request a code change.", style="#a0a0a0"),
            Text("Enter sends  ·  Esc cancels a run  ·  Ctrl+D quits  ·  Ctrl+L clears", style="#575757"),
        )
        super().__init__(body, classes="welcome")

class UserMessage(Static):
    """A user prompt with long pasted chunks and images hidden behind compact links."""

    COMPACT_PASTE_AFTER = 100

    def __init__(
        self,
        content: str,
        *,
        pasted_chunks: tuple[str, ...] = (),
        images: Sequence[ImageAttachment] = (),
    ) -> None:
        self._hidden_content: dict[str, str] = {}
        self._images = {image.number: image for image in images}
        super().__init__(
            self._compact_content(content, pasted_chunks),
            classes="message user-message",
        )

    def _compact_content(self, content: str, pasted_chunks: tuple[str, ...]) -> Text:
        self._hidden_content.clear()
        replacements: list[tuple[int, int, Text]] = []
        occupied: list[tuple[int, int]] = []

        for chunk in pasted_chunks:
            candidates = (chunk, chunk.strip(), chunk.lstrip(), chunk.rstrip())
            displayed_chunk = next(
                (candidate for candidate in candidates if candidate in content),
                "",
            )
            if (
                len(displayed_chunk) <= self.COMPACT_PASTE_AFTER
                and "\n" not in displayed_chunk
                and "\r" not in displayed_chunk
            ):
                continue
            start = content.find(displayed_chunk)
            while start >= 0 and _overlaps(start, start + len(displayed_chunk), occupied):
                start = content.find(displayed_chunk, start + 1)
            if start < 0:
                continue
            end = start + len(displayed_chunk)
            key = str(len(self._hidden_content))
            self._hidden_content[key] = displayed_chunk
            occupied.append((start, end))
            replacements.append(
                (
                    start,
                    end,
                    Text(
                        f"[{len(displayed_chunk):,} chars]",
                        style=Style(
                            color="#87b5b1",
                            bold=True,
                            underline=True,
                            meta={"@click": f"open_content('{key}')"},
                        ),
                    ),
                )
            )

        for match in IMAGE_MARKER_RE.finditer(content):
            number = match.group(1)
            if number not in self._images:
                continue
            start, end = match.span()
            if _overlaps(start, end, occupied):
                continue
            occupied.append((start, end))
            replacements.append(
                (
                    start,
                    end,
                    Text(
                        match.group(0),
                        style=Style(
                            color="#87b5b1",
                            bold=True,
                            underline=True,
                            meta={"@click": f"open_image('{number}')"},
                        ),
                    ),
                )
            )

        if not replacements:
            return Text(content)

        display = Text()
        cursor = 0
        for start, end, chip in sorted(replacements, key=lambda item: item[0]):
            display.append(content[cursor:start])
            display.append(chip)
            cursor = end
        display.append(content[cursor:])
        return display

    def action_open_content(self, key: str) -> None:
        content = self._hidden_content.get(key)
        if content is not None:
            self.app.push_screen(ContentModal(content))

    def action_open_image(self, number: str) -> None:
        image = self._images.get(number)
        if image is not None:
            self.app.push_screen(ImageModal(image))


class AssistantMessage(Static):
    def __init__(self, content: str = "") -> None:
        super().__init__(classes="message assistant-message")
        self.set_content(content)

    def set_content(self, content: str) -> None:
        self.message_text = content
        self.update(
            Group(
                Text("◆  SYMPHONY", style="bold #d0d0d0"),
                themed_markdown(content or " "),
            )
        )

def _overlaps(start: int, end: int, occupied: Sequence[tuple[int, int]]) -> bool:
    return any(
        start < occupied_end and end > occupied_start
        for occupied_start, occupied_end in occupied
    )

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
        if not self._working:
            self._animation_timer.pause()

    def set_text(self, value: str) -> None:
        self._working = False
        if self._animation_timer is not None:
            self._animation_timer.pause()
        self.update(Text(f"✻  {value}", style="#666666"))

    def set_working(self, detail: str = "") -> None:
        """Show a moving color gradient while a model request is retrying."""
        self._working = True
        self._working_detail = detail
        if self._animation_timer is not None:
            self._animation_timer.resume()
        self._render_working()

    def _advance_gradient(self) -> None:
        if not self._working:
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
        self._thinking.display = False
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


class Notice(Static):
    COLORS = {
        "info": "#707070",
        "warning": "#d7a84b",
        "error": "#e06c75",
        "success": "#70a879",
    }

    def __init__(self, text: str, tone: str = "info") -> None:
        color = self.COLORS.get(tone, self.COLORS["info"])
        super().__init__(Text(f"  {text}", style=color), classes=f"notice {tone}")


class TranscriptSurface:
    """TranscriptView implementation mixed into CodingAgentApp."""

    def _follow_transcript_tail(
        self, transcript: VerticalScroll, *, was_at_end: bool
    ) -> None:
        """Keep following live output unless the user has scrolled away."""
        if was_at_end:
            self.call_after_refresh(transcript.scroll_end, animate=False)

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
        self._thinking.display = True
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
                self._thinking.display = False
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
            self._thinking.display = False
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
        transcript = self.query_one("#transcript", VerticalScroll)
        was_at_end = transcript.is_vertical_scroll_end
        widget = self._tools.get(call_id)
        if widget is None:
            self.add_tool(call_id, "tool")
            widget = self._tools[call_id]
        if status == "running":
            widget.set_running(arguments)
        elif status == "done":
            widget.set_result(result)
        else:
            widget.set_arguments(arguments, raw_arguments)
        self._follow_transcript_tail(transcript, was_at_end=was_at_end)

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
