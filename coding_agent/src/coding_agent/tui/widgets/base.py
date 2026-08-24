"""Core conversation and prompt widgets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

from coding_agent.tui.images import (
    IMAGE_MARKER_RE,
    ImageAttachment,
    dropped_image_paths,
)
from coding_agent.tui.modal.base import ContentModal
from coding_agent.tui.modal.image import ImageModal
from coding_agent.tui.theme import themed_markdown


class TopBar(Static):
    """Terminal header with a quiet workspace label and model chip."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._workspace = ""
        self._model = ""
        super().__init__(*args, **kwargs)

    def compose(self):  # type: ignore[no-untyped-def]
        yield Static("◆  symphony", id="topbar-product")
        yield Static(id="topbar-workspace")
        yield Static("model", id="topbar-model")

    def set_context(self, workspace: Path, model: str = "") -> None:
        self._workspace = str(workspace)
        self._model = model
        self.query_one("#topbar-workspace", Static).update(
            Text(self._workspace, style="#777777")
        )
        chip = Text(f" {model or 'no model'} ", style="#a0a0a0")
        self.query_one("#topbar-model", Static).update(chip)


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


class PromptInput(TextArea):
    """Multiline prompt editor with compact handling for large pastes and images."""

    class Submitted(Message):
        def __init__(self, text_area: "PromptInput") -> None:
            self.input = text_area
            super().__init__()

    COMPACT_PASTE_AFTER = UserMessage.COMPACT_PASTE_AFTER

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._pasted_chunks: list[tuple[str, str]] = []
        self._images: list[ImageAttachment] = []
        self._image_seq = 0
        self.submit_on_enter = False
        super().__init__(*args, **kwargs)

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, value: str) -> None:
        self.load_text(value)

    @property
    def cursor_position(self) -> int:
        return self.document.get_index_from_location(self.cursor_location)

    @cursor_position.setter
    def cursor_position(self, value: int) -> None:
        self.cursor_location = self.document.get_location_from_index(value)

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    def on_key(self, event: events.Key) -> None:
        """Route Enter to the active interaction channel."""
        if event.key != "enter":
            return
        if self.submit_on_enter:
            self.action_submit()
        else:
            from coding_agent.tui.slash_menu import SlashMenu

            menu = self.app.query_one("#slash-menu", SlashMenu)
            if not menu.display or not menu.selected_value:
                return
            self.app._choose_menu_option(menu, submit=True)
        event.prevent_default()
        event.stop()

    @property
    def pasted_chunks(self) -> tuple[str, ...]:
        return tuple(content for _marker, content in self._pasted_chunks)

    @property
    def images(self) -> tuple[ImageAttachment, ...]:
        return tuple(self._images)

    def expanded_value(self, value: str | None = None) -> str:
        """Restore compact markers to the clipboard text sent to the agent."""
        expanded = self.value if value is None else value
        for marker, content in self._pasted_chunks:
            expanded = expanded.replace(marker, content, 1)
        return expanded

    def take_pasted_chunks(self) -> tuple[str, ...]:
        chunks = self.pasted_chunks
        self._pasted_chunks.clear()
        return chunks

    def take_images(self) -> tuple[ImageAttachment, ...]:
        images = self.images
        self._images.clear()
        self._image_seq = 0
        return images

    def _insert_paste(self, content: str) -> None:
        if not content:
            return
        paths = dropped_image_paths(content)
        if paths:
            for path in paths:
                self._attach_image(path)
            return
        start, end = self.selection.start, self.selection.end
        should_compact = (
            len(content) > self.COMPACT_PASTE_AFTER or "\n" in content or "\r" in content
        )
        if not should_compact:
            self.replace(content, start, end)
            return
        marker = f"[{len(content):,} chars]"
        self.replace(marker, start, end)
        self._pasted_chunks.append((marker, content))

    def _attach_image(self, path: Path) -> None:
        self._image_seq += 1
        marker = f"[Image {self._image_seq}]"
        self._images.append(ImageAttachment.from_path(path, marker))
        start, end = self.selection.start, self.selection.end
        index = self.document.get_index_from_location(start)
        prefix = ""
        if index > 0 and self.value[index - 1] not in " \n\t":
            prefix = " "
        self.replace(f"{prefix}{marker} ", start, end)

    def _on_paste(self, event: Any) -> None:
        self._insert_paste(str(event.text))
        event.prevent_default()
        event.stop()

    def action_paste(self) -> None:
        self._insert_paste(self.app.clipboard)

    def on_click(self, event: Any) -> None:
        position = self.cursor_position
        search_from = 0
        for marker, content in self._pasted_chunks:
            start = self.value.find(marker, search_from)
            if start < 0:
                continue
            end = start + len(marker)
            if start <= position <= end:
                self.app.push_screen(ContentModal(content))
                event.stop()
                return
            search_from = end
        search_from = 0
        for image in self._images:
            start = self.value.find(image.marker, search_from)
            if start < 0:
                continue
            end = start + len(image.marker)
            if start <= position <= end:
                self.app.push_screen(ImageModal(image))
                event.stop()
                return
            search_from = end


def _overlaps(start: int, end: int, occupied: Sequence[tuple[int, int]]) -> bool:
    return any(
        start < occupied_end and end > occupied_start
        for occupied_start, occupied_end in occupied
    )
