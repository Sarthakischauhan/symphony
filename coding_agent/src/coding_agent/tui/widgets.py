"""Conversation, composer, and tool-call widgets for the coding-agent TUI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Static, TextArea

from coding_agent.tui.images import (
    IMAGE_MARKER_RE,
    ImageAttachment,
    ImageModal,
    dropped_image_paths,
)
from coding_agent.tui.modal import ContentModal
from coding_agent.tui.theme import themed_markdown
from coding_agent.utils.diff import diff_stats, make_unified_diff
from coding_agent.utils.text import clip_text, compact_json

# --- header.py ---
class BashToolHeader(Horizontal, can_focus=True):
    """Focusable Bash timeline header that toggles its output."""

    class Toggle(Message):
        pass

    def _on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Toggle())

    def _on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.post_message(self.Toggle())

# --- base.py ---
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

# --- composer.py ---
class Composer(Container):
    """Input surface with an always-visible interaction hint."""

    def compose(self):  # type: ignore[no-untyped-def]
        from coding_agent.tui.slash_menu import SlashMenu

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

# --- status.py ---
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

# --- base.py ---
class ToolCallWidget(Collapsible):
    """A collapsible tool lifecycle card that updates as arguments/results arrive."""

    LABELS = {
        "bash": ("Bash", "$"),
        "search": ("Search", "⌕"),
        "write_file": ("Write", "+"),
        "generate_image": ("Image", "└"),
        "patch": ("Edit", "±"),
    }

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._body = self._make_body()
        self._tool_label = Static(classes="tool-call-label")
        self._tool_command = Static(classes="tool-call-command")
        self._tool_status = Static(classes="tool-call-status")
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments: dict[str, Any] = {}
        self.raw_arguments = ""
        self.result = ""
        self.status = "preparing"
        super().__init__(
            self._body,
            title="Tool",
            collapsed=True,
            collapsed_symbol="",
            expanded_symbol="",
            classes="tool-call",
        )
        self.refresh_content()

    def _make_body(self) -> Static:
        return Static()

    def compose(self):  # type: ignore[no-untyped-def]
        # Keep CollapsibleTitle in the DOM for keyboard/accessibility compatibility;
        # the timeline header is the visible control shared by every tool.
        yield self._title
        with BashToolHeader(classes="tool-call-header"):
            yield self._tool_label
            yield self._tool_command
            yield self._tool_status
        with self.Contents():
            yield self._body

    def on_bash_tool_header_toggle(self, event: BashToolHeader.Toggle) -> None:
        event.stop()
        self.collapsed = not self.collapsed

    def _watch_collapsed(self, collapsed: bool) -> None:
        # Collapsible scrolls itself into view after every state change. The
        # transcript already owns tail-following, so that competing scroll
        # produces visible jumps as tools complete.
        self._update_collapsed(collapsed)
        if collapsed:
            self.post_message(self.Collapsed(self))
        else:
            self.post_message(self.Expanded(self))
        self._body.display = not collapsed
        self.refresh_content()

    def _disclosure_symbol(self) -> str:
        return "▸" if self.collapsed else "▾"

    def set_arguments(self, arguments: Mapping[str, Any] | None, raw: str = "") -> None:
        self.arguments = dict(arguments or {})
        self.raw_arguments = raw
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        self.arguments = dict(arguments or {})
        self.refresh_content()

    def set_result(self, result: Any) -> None:
        self.status = "failed" if str(result).startswith("error:") else "done"
        self.result = str(result or "")
        self.refresh_content()

    def _tool_title(self) -> tuple[str, str]:
        return self.LABELS.get(self.tool_name, (self.tool_name.replace("_", " ").title(), "›"))

    def _summary(self) -> str:
        if self.tool_name == "bash":
            return str(self.arguments.get("command") or self.raw_arguments)
        if self.tool_name == "search":
            return str(
                self.arguments.get("query")
                or self.arguments.get("pattern")
                or compact_json(self.arguments)
            )
        if self.tool_name in {"write_file", "patch", "generate_image", "read_file"}:
            return str(self.arguments.get("path") or compact_json(self.arguments))
        return compact_json(self.arguments) or self.raw_arguments

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        lines = self.result.splitlines()
        if self.tool_name == "bash":
            return clip_text("\n".join(lines[-4:]), 360)
        return clip_text(self.result, 260)

    def _body_rows(self) -> list[Any]:
        rows: list[Any] = []
        summary = clip_text(self._summary(), 300)
        if summary:
            rows.append(Text(summary, style="#a4a4a4"))
        result = self._result_summary()
        if result:
            _label, icon = self._tool_title()
            result_color = "#d66b73" if self.status == "failed" else "#666666"
            rows.append(Text(f"{icon}  {result}", style=result_color))
        return rows

    def refresh_content(self) -> None:
        label, _icon = self._tool_title()
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        summary = clip_text(self._summary(), 140)
        title = f"{marker}  {label}"
        if summary:
            title = f"{title}  {summary}"
        if self.status in {"preparing", "running"}:
            title = f"{title}   {self.status}"
        self.title = title
        self._tool_label.update(f"{self._disclosure_symbol()} {marker}  {label}")
        self._tool_command.update(summary)
        self._tool_status.update(self.status)
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        self._body.update(Group(*self._body_rows()))


IMAGE_CHIP = "[Image 1]"


class ImageChipBody(Static):
    """Tool-result body that opens an image modal when clicked."""

    def action_open_image(self) -> None:
        self._open_owner_preview()

    def on_click(self, event: object) -> None:
        if self._open_owner_preview():
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()

    def _open_owner_preview(self) -> bool:
        node = self.parent
        while node is not None:
            method = getattr(node, "open_preview", None)
            if callable(method):
                return bool(method())
            node = node.parent
        return False


class GenerateImageWidget(ToolCallWidget):
    """Path-oriented generate_image card with a clickable `[Image 1]` preview."""

    def _make_body(self) -> Static:
        return ImageChipBody()

    def _tool_title(self) -> tuple[str, str]:
        return ("Image", "└")

    def _summary(self) -> str:
        return str(self.arguments.get("path") or self.raw_arguments)

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        if self.result.startswith("error:"):
            return self.result
        return self.result.splitlines()[0]

    def set_result(self, result: Any) -> None:
        super().set_result(result)
        if self.status == "done" and self.is_attached:
            self.collapsed = False

    def _body_rows(self) -> list[Any]:
        rows: list[Any] = []
        summary = clip_text(self._summary(), 300)
        if summary:
            rows.append(Text(summary, style="#a4a4a4"))
        if self.status == "failed":
            if self.result:
                rows.append(Text(f"└  {self.result}", style="#d66b73"))
            return rows
        if self.status == "done":
            chip = Text()
            chip.append(IMAGE_CHIP, style=Style(color="#87b5b1", bold=True, underline=True))
            detail = self._result_summary()
            if detail:
                chip.append(f"  {detail}", style="#666666")
            rows.append(chip)
        return rows

    def open_preview(self) -> bool:
        workspace = getattr(self.app, "workspace", None)
        path = str(self.arguments.get("path") or "")
        if workspace is None or not path or self.status == "failed":
            return False
        try:
            root = Path(workspace).resolve()
            target = (root / path).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return False
            image = ImageAttachment.from_path(target, IMAGE_CHIP)
        except OSError:
            return False
        self.app.push_screen(ImageModal(image))
        return True

# --- read_file.py ---
class ReadFileWidget(ToolCallWidget):
    """Compact, path-oriented presentation for the read_file tool."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Read", "└")

    def _summary(self) -> str:
        path = self.arguments.get("path")
        if not path:
            return self.raw_arguments
        offset = int(self.arguments.get("offset") or 1)
        limit = int(self.arguments.get("limit") or 0)
        window = ""
        if offset != 1 or limit:
            end = offset + limit - 1 if limit else "…"
            window = f"  lines {offset}–{end}"
        return f"{path}{window}"

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        if self.result.startswith("error:"):
            return self.result
        if self.result.startswith("Read image ") or "[image:" in self.result:
            return self.result.splitlines()[0]
        count = len(self.result.splitlines())
        size = len(self.result.encode("utf-8"))
        return f"Read {count} lines ({size:,} bytes)"

# --- bash.py ---
class BashToolWidget(ToolCallWidget):
    """Bash-specific row with command and lifecycle status on one line."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._bash_label = Static(classes="bash-tool-label")
        self._bash_command = Static(classes="bash-tool-command")
        self._bash_status = Static(classes="bash-tool-status")
        super().__init__(call_id, tool_name)
        self.add_class("bash-tool")
        self._body.add_class("bash-tool-body")

    def compose(self):  # type: ignore[no-untyped-def]
        with BashToolHeader(classes="bash-tool-header"):
            yield self._bash_label
            yield self._bash_command
            yield self._bash_status
        yield self._body

    def refresh_content(self) -> None:
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        self._bash_label.update(f"{self._disclosure_symbol()} {marker}  Bash")
        self._bash_command.update(clip_text(self._summary(), 180))
        self._bash_status.update(self.status)
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        self._body.update(Group(*self._body_rows()))

# --- patch.py ---
class PatchDiffWidget(ToolCallWidget):
    """Unified diff presentation for the exact-text patch tool."""

    MAX_DIFF_LINES = 80

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__(call_id, tool_name)
        self.add_class("diff-tool")

    def _diff(self) -> list[str]:
        old = str(self.arguments.get("old_str") or "")
        new = str(self.arguments.get("new_str") or "")
        if not old and not new:
            return []
        path = str(self.arguments.get("path") or "file")
        return make_unified_diff(old, new, path)

    def _stats(self, diff: list[str]) -> tuple[int, int]:
        return diff_stats(diff)

    def refresh_content(self) -> None:
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        path = str(self.arguments.get("path") or "")
        diff = self._diff()
        additions, deletions = self._stats(diff)

        title = f"{marker}  Update"
        if path:
            title = f"{title} ({path})"
        if diff:
            title = f"{title}  +{additions} -{deletions}"
        if self.status in {"preparing", "running"}:
            title = f"{title}   {self.status}"
        self.title = title
        summary = path
        if diff:
            stats = f"+{additions} -{deletions}"
            summary = f"{summary}  {stats}" if summary else stats
        self._tool_label.update(
            f"{self._disclosure_symbol()} {marker}  Update"
        )
        self._tool_command.update(summary)
        self._tool_status.update(self.status)
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        rows: list[Any] = []

        visible = diff[: self.MAX_DIFF_LINES]
        for line in visible:
            if line.startswith("@@"):
                rows.append(Text(line, style="#6688a8"))
            elif line.startswith("+"):
                rows.append(Text(line, style="#8fc49a on #203026"))
            elif line.startswith("-"):
                rows.append(Text(line, style="#df8b91 on #352225"))
            else:
                rows.append(Text(line, style="#686868"))
        if len(diff) > self.MAX_DIFF_LINES:
            hidden = len(diff) - self.MAX_DIFF_LINES
            rows.append(Text(f"… {hidden} diff lines hidden", style="#555555"))

        if self.result:
            result_color = "#d66b73" if self.status == "failed" else "#626262"
            rows.append(Text(f"└  {clip_text(self.result, 260)}", style=result_color))
        self._body.update(Group(*rows))

# --- factory.py ---
def make_tool_widget(call_id: str, tool_name: str) -> ToolCallWidget:
    if tool_name == "spawn_agent":
        from coding_agent.tui.subagent import SubagentWidget

        return SubagentWidget(call_id, tool_name)
    if tool_name == "bash":
        return BashToolWidget(call_id, tool_name)
    if tool_name == "read_file":
        return ReadFileWidget(call_id, tool_name)
    if tool_name == "generate_image":
        return GenerateImageWidget(call_id, tool_name)
    if tool_name == "patch":
        return PatchDiffWidget(call_id, tool_name)
    return ToolCallWidget(call_id, tool_name)

__all__ = [
    "AssistantMessage",
    "BashToolHeader",
    "BashToolWidget",
    "Composer",
    "GenerateImageWidget",
    "Notice",
    "PatchDiffWidget",
    "PromptInput",
    "ReadFileWidget",
    "ReasoningWidget",
    "RunProcess",
    "ThinkingStatus",
    "ToolCallWidget",
    "TopBar",
    "UserMessage",
    "Welcome",
    "make_tool_widget",
]
