"""Transcript message widgets and shared text helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from coding_agent.tui.screens.modal import ContentModal
from coding_agent.tui.theme import SYMPHONY_COLORS, themed_markdown
from coding_agent.tui.tools.images import IMAGE_MARKER_RE, ImageAttachment, ImageModal

# Accent glyph that opens every user prompt in the transcript (mock: purple `>`).
USER_PROMPT_GLYPH = ">"
USER_PROMPT_GUTTER = 3


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

class Welcome(Static):
    def __init__(self, workspace: Path) -> None:
        body = Group(
            Text("Symphony", style="bold " + SYMPHONY_COLORS["foreground"]),
            Text("Coding agent", style=SYMPHONY_COLORS["muted"]),
            Text(""),
            Text(f"  {workspace}", style=SYMPHONY_COLORS["muted_dim"]),
            Text(""),
            Text(
                "Describe a task, ask a question, or request a code change.",
                style=SYMPHONY_COLORS["muted"],
            ),
            Text(
                "Ctrl+↵ sends  ·  Enter adds a line  ·  Tab switches mode  ·  "
                "Esc cancels a run  ·  Ctrl+D quits  ·  Ctrl+L clears",
                style=SYMPHONY_COLORS["muted_dim"],
            ),
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
        self.message_text = content
        self._hidden_content: dict[str, str] = {}
        self._images = {image.number: image for image in images}
        super().__init__(
            self._with_prompt_glyph(self._compact_content(content, pasted_chunks)),
            classes="message user-message",
        )

    def archive_text(self) -> str:
        return f"USER\n{self.message_text}"

    @staticmethod
    def _with_prompt_glyph(content: Text) -> Table:
        """Lay the prompt text beside an accent `>` so wrapped lines stay aligned."""
        row = Table.grid(expand=True, padding=0)
        row.add_column(width=USER_PROMPT_GUTTER, no_wrap=True)
        row.add_column(ratio=1)
        row.add_row(
            Text(USER_PROMPT_GLYPH, style="bold " + SYMPHONY_COLORS["accent"]),
            content,
        )
        return row

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
    def __init__(self, content: str = "", *, streaming: bool = False) -> None:
        self._streaming = False
        super().__init__(classes="message assistant-message")
        self.set_content(content, streaming=streaming)

    def set_content(self, content: str, *, streaming: bool = False) -> None:
        self.message_text = content
        self._streaming = streaming
        body = Text(content or " ") if streaming else themed_markdown(content or " ")
        self.update(
            Group(
                Text("◆  SYMPHONY", style="bold #d0d0d0"),
                body,
            )
        )

    def finish_stream(self) -> None:
        if self._streaming:
            self.set_content(self.message_text)

    def archive_text(self) -> str:
        return f"SYMPHONY\n{self.message_text}"

def _overlaps(start: int, end: int, occupied: Sequence[tuple[int, int]]) -> bool:
    return any(
        start < occupied_end and end > occupied_start
        for occupied_start, occupied_end in occupied
    )


class Notice(Static):
    COLORS = {
        "info": "#707070",
        "warning": "#d7a84b",
        "error": "#e06c75",
        "success": "#70a879",
    }

    def __init__(self, text: str, tone: str = "info") -> None:
        self.message_text = text
        color = self.COLORS.get(tone, self.COLORS["info"])
        super().__init__(Text(f"  {text}", style=color), classes=f"notice {tone}")

    def archive_text(self) -> str:
        return self.message_text


class RunSummary(Static):
    """User-message-like purple block for a summary emitted during a run."""

    def __init__(
        self,
        summary: str,
        *,
        label: str = "Summary",
        event_type: str = "run_summary",
    ) -> None:
        self.summary = summary
        self.label = label
        heading = Text(f"◆  {label}  ·  {event_type}", style="bold #c5a9e6")
        body = Text(summary, style="#c2b5cf")
        super().__init__(Group(heading, body), classes="message run-summary")

    def archive_text(self) -> str:
        return f"{self.label}\n{self.summary}"
