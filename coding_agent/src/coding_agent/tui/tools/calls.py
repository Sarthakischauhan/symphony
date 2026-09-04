"""Tool-call widgets for the coding-agent TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Collapsible, Static

from coding_agent.tui.screens.modal import ContentModal
from coding_agent.tui.tools.diff import diff_stats, make_unified_diff
from coding_agent.tui.tools.images import ImageAttachment, ImageModal
from coding_agent.tui.transcript.messages import clip_text, compact_json


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
        self._body_dirty = True
        self._header_values: tuple[str, str, str] | None = None
        self._styled_status: str | None = None
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
        self._body_dirty = True
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        self.arguments = dict(arguments or {})
        self._body_dirty = True
        self.refresh_content()

    def set_result(self, result: Any) -> None:
        self.status = "failed" if str(result).startswith("error:") else "done"
        self.result = str(result or "")
        self._body_dirty = True
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

    def _marker(self) -> str:
        return {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")

    def _refresh_status_class(self) -> None:
        if self._styled_status == self.status:
            return
        if self._styled_status is not None:
            self.remove_class(f"status-{self._styled_status}")
        self.add_class(f"status-{self.status}")
        self._styled_status = self.status

    def _refresh_header(self, label: str, summary: str) -> None:
        values = (
            f"{self._disclosure_symbol()} {self._marker()}  {label}",
            summary,
            self.status,
        )
        if values == self._header_values:
            return
        old = self._header_values
        if old is None or old[0] != values[0]:
            self._tool_label.update(values[0], layout=False)
        if old is None or old[1] != values[1]:
            self._tool_command.update(values[1], layout=False)
        if old is None or old[2] != values[2]:
            self._tool_status.update(values[2], layout=False)
        self._header_values = values

    def _refresh_body(self) -> None:
        if self.collapsed or not self._body_dirty:
            return
        self._body.update(Group(*self._body_rows()))
        self._body_dirty = False

    def refresh_content(self) -> None:
        label, _icon = self._tool_title()
        summary = clip_text(self._summary(), 140)
        self._refresh_header(label, summary)
        self._refresh_status_class()
        self._refresh_body()

    def snapshot(self) -> ToolCallSnapshot:
        label, _icon = self._tool_title()
        return ToolCallSnapshot(
            call_id=self.call_id,
            tool_name=self.tool_name,
            label=label,
            detail=clip_text(self._summary(), 300),
            status=self.status,
            result=self._result_summary(),
        )


@dataclass(frozen=True)
class ToolCallSnapshot:
    """Display data retained after a live tool card is folded away."""

    call_id: str
    tool_name: str = "tool"
    label: str = "Tool"
    detail: str = ""
    status: str = "done"
    result: str = ""

    def as_text(self) -> str:
        marker = "×" if self.status == "failed" else "✓"
        line = f"{marker}  {self.label}"
        if self.detail:
            line = f"{line}  {self.detail}"
        if self.result:
            line = f"{line}\n   {self.result}"
        return line


class ToolCallSummary(Static, can_focus=True):
    """One-line Explored row standing in for folded ToolCallWidgets.

    Click or press Enter to open the folded tools' snapshots in a modal.
    """

    def __init__(self) -> None:
        self.calls: list[ToolCallSnapshot] = []
        super().__init__(self._line(), classes="tool-call-summary")

    @property
    def call_ids(self) -> list[str]:
        return [call.call_id for call in self.calls]

    @property
    def count(self) -> int:
        return len(self.calls)

    def add_call(self, call: str | ToolCallWidget | ToolCallSnapshot) -> None:
        if isinstance(call, ToolCallWidget):
            snapshot = call.snapshot()
        elif isinstance(call, ToolCallSnapshot):
            snapshot = call
        else:
            snapshot = ToolCallSnapshot(call_id=call)
        if snapshot.call_id not in self.call_ids:
            self.calls.append(snapshot)
        from textual._context import NoActiveAppError

        try:
            self.update(self._line())
        except NoActiveAppError:
            pass

    def snapshot_text(self) -> str:
        return "\n\n".join(call.as_text() for call in self.calls)

    def archive_text(self) -> str:
        return self.snapshot_text()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.open_details()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.open_details()

    def open_details(self) -> None:
        content = self.snapshot_text() or "No folded tool calls."
        self.app.push_screen(ContentModal(content))

    def _line(self) -> Text:
        line = Text()
        line.append("[ ", style="#666666")
        line.append("Explored", style="#d7a84b")
        line.append(f"       {self.count} tools]", style="#666666")
        return line


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
        if self.status == "done":
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
        values = (
            f"{self._disclosure_symbol()} {self._marker()}  Bash",
            clip_text(self._summary(), 180),
            self.status,
        )
        if values != self._header_values:
            old = self._header_values
            if old is None or old[0] != values[0]:
                self._bash_label.update(values[0], layout=False)
            if old is None or old[1] != values[1]:
                self._bash_command.update(values[1], layout=False)
            if old is None or old[2] != values[2]:
                self._bash_status.update(values[2], layout=False)
            self._header_values = values
        self._refresh_status_class()
        self._refresh_body()

# --- patch.py ---
class PatchDiffWidget(ToolCallWidget):
    """Unified diff presentation for the exact-text patch tool."""

    MAX_DIFF_LINES = 80

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._diff_key: tuple[str, str, str] | None = None
        self._diff_cache: list[str] = []
        super().__init__(call_id, tool_name)
        self.add_class("diff-tool")

    def _diff(self) -> list[str]:
        old = str(self.arguments.get("old_str") or "")
        new = str(self.arguments.get("new_str") or "")
        path = str(self.arguments.get("path") or "file")
        key = (path, old, new)
        if key == self._diff_key:
            return self._diff_cache
        self._diff_key = key
        if not old and not new:
            self._diff_cache = []
            return []
        self._diff_cache = make_unified_diff(old, new, path)
        return self._diff_cache

    def _stats(self, diff: list[str]) -> tuple[int, int]:
        return diff_stats(diff)

    def refresh_content(self) -> None:
        path = str(self.arguments.get("path") or "")
        diff = self._diff()
        additions, deletions = self._stats(diff)
        summary = path
        if diff:
            stats = f"+{additions} -{deletions}"
            summary = f"{summary}  {stats}" if summary else stats
        self._refresh_header("Update", summary)
        self._refresh_status_class()
        if self.collapsed or not self._body_dirty:
            return
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
        self._body_dirty = False

# --- factory.py ---
def make_tool_widget(call_id: str, tool_name: str) -> ToolCallWidget:
    if tool_name == "spawn_agent":
        from coding_agent.tui.runtime.subagent import SubagentWidget

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
