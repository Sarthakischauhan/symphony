"""Tool-call widgets for the coding-agent TUI."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, Mapping

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Collapsible, Static

from coding_agent.tui.motion import enter_row
from coding_agent.tui.tools.activity import parse_activity, strip_activity_json, take_activity
from coding_agent.tui.tools.diff import make_unified_diff, patch_summary
from coding_agent.tui.tools.images import ImageAttachment, ImageModal
from coding_agent.tui.tools.labels import (
    TOOL_LABELS,
    generate_image_result,
    header_command,
    read_file_detail,
    read_file_result,
    result_preview,
    tool_detail,
    tool_label,
)
from coding_agent.tui.tools.snapshots import ToolCallSnapshot
from coding_agent.tui.transcript.messages import clip_text

IMAGE_CHIP = "[Image 1]"


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

    LABELS = TOOL_LABELS

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._body = self._make_body()
        self._tool_label = Static(classes="tool-call-label", markup=False)
        self._tool_command = Static(classes="tool-call-command", markup=False)
        self._tool_status = Static(classes="tool-call-status", markup=False)
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments: dict[str, Any] = {}
        self.raw_arguments = ""
        self.result = ""
        self.status = "preparing"
        self._started_at = monotonic()
        self._duration: float | None = None
        self.activity_verb = ""
        self.activity_reason = ""
        self.activity_group = ""
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

    def on_mount(self) -> None:
        enter_row(self, duration=0.14)

    def _make_body(self) -> Static:
        return Static(markup=False)

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
        self._apply_activity(take_activity(self.arguments))
        self.raw_arguments = strip_activity_json(raw) if raw else raw
        self._body_dirty = True
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        self.arguments = dict(arguments or {})
        self._apply_activity(take_activity(self.arguments))
        self._body_dirty = True
        self.refresh_content()

    def _apply_activity(self, activity: Any) -> None:
        self.activity_verb = activity.verb
        self.activity_reason = activity.reason
        self.activity_group = activity.group

    def set_activity(self, activity: Mapping[str, Any] | None) -> None:
        self._apply_activity(parse_activity(activity))
        self.refresh_content()

    def set_result(self, result: Any) -> None:
        if self._duration is None:
            self._duration = max(0.0, monotonic() - self._started_at)
        self.status = "failed" if str(result).startswith("error:") else "done"
        self.result = str(result or "")
        self._body_dirty = True
        self.refresh_content()

    def _tool_title(self) -> tuple[str, str]:
        return tool_label(self.tool_name)

    def _summary(self) -> str:
        return tool_detail(self.tool_name, self.arguments, self.raw_arguments)

    def _result_summary(self) -> str:
        return result_preview(self.tool_name, self.result)

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
            header_command(self.activity_reason, summary, 140),
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
        self._refresh_header(label, clip_text(self._summary(), 140))
        self._refresh_status_class()
        self._refresh_body()

    @property
    def duration(self) -> float | None:
        return self._duration

    def snapshot(self) -> ToolCallSnapshot:
        label, _icon = self._tool_title()
        return ToolCallSnapshot(
            call_id=self.call_id,
            tool_name=self.tool_name,
            label=label,
            detail=clip_text(self._summary(), 300),
            status=self.status,
            result=self._result_summary(),
            activity_verb=self.activity_verb,
            activity_reason=self.activity_reason,
            activity_group=self.activity_group,
            duration=self._duration,
        )


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
        return generate_image_result(self.result)

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
            candidate = Path(path).expanduser()
            target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if not target.is_file():
                return False
            image = ImageAttachment.from_path(target, IMAGE_CHIP)
        except OSError:
            return False
        self.app.push_screen(ImageModal(image))
        return True


class ReadFileWidget(ToolCallWidget):
    """Compact, path-oriented presentation for the read_file tool."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Read", "└")

    def _summary(self) -> str:
        return read_file_detail(self.arguments, self.raw_arguments)

    def _result_summary(self) -> str:
        return read_file_result(self.result)


class BashToolWidget(ToolCallWidget):
    """Bash-specific row with command and lifecycle status on one line."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._bash_label = Static(classes="bash-tool-label", markup=False)
        self._bash_command = Static(classes="bash-tool-command", markup=False)
        self._bash_status = Static(classes="bash-tool-status", markup=False)
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
            header_command(self.activity_reason, clip_text(self._summary(), 180), 180),
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
        self._diff_cache = make_unified_diff(old, new, path) if old or new else []
        return self._diff_cache

    def refresh_content(self) -> None:
        path = str(self.arguments.get("path") or "")
        diff = self._diff()
        self._refresh_header("Update", patch_summary(path, diff))
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
