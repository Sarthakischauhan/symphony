"""Base tool-call timeline widget."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.widgets import Collapsible, Static

from coding_agent.tui.images import ImageAttachment, ImageModal
from coding_agent.tui.widgets.tools.header import BashToolHeader
from coding_agent.utils.text import clip_text, compact_json


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
        self.status = "failed" if str(result).startswith(("error:", "exit=")) else "done"
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
