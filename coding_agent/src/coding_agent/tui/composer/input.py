"""Prompt editor and composer chrome."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.widgets import Static, TextArea

from coding_agent.tui.screens.modal import ContentModal
from coding_agent.tui.tools.images import ImageAttachment, ImageModal, dropped_image_paths
from coding_agent.tui.transcript import UserMessage

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
            from coding_agent.tui.composer.slash_menu import SlashMenu

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


class Composer(Container):
    """Input surface with an always-visible interaction hint."""

    def compose(self):  # type: ignore[no-untyped-def]
        from coding_agent.tui.composer.slash_menu import SlashMenu

        yield SlashMenu(id="approval-menu")
        yield PromptInput(
            placeholder="Ask Symphony to build, fix, or explain…",
            id="prompt",
            soft_wrap=True,
            show_line_numbers=False,
        )
        with Horizontal(id="composer-footer"):
            yield Static("BUILD · Tab mode", id="composer-mode")
            yield Static("Ctrl+↵ send   Enter line break   Esc cancel", id="composer-hint")
