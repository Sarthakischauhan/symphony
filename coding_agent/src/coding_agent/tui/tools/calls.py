"""Tool-call widgets for the coding-agent TUI."""

from __future__ import annotations

from difflib import unified_diff
import re
from time import monotonic
from typing import Any, Mapping

from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from coding_agent.tui.motion import enter_row
from coding_agent.tui.tools.activity import parse_activity, strip_activity_json, take_activity
from coding_agent.tui.tools.labels import (
    TOOL_LABELS,
    generate_image_result,
    header_target,
    read_file_detail,
    read_file_result,
    result_preview,
    tool_detail,
    tool_header_text,
    tool_label,
)
from coding_agent.tui.tools.snapshots import ToolCallSnapshot
from coding_agent.tui.transcript.messages import clip_text


class ToolCallWidget(Vertical, can_focus=False, can_focus_children=False):
    """A display-only tool lifecycle row that updates as arguments/results arrive.

    The row is one status-colored header line. It has no click, key, or
    expand handling; completed rows fold into the Explored summary.
    """

    LABELS = TOOL_LABELS
    HEADER_LIMIT = 140

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._tool_label = Static(classes="tool-call-label", markup=False)
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
        self._header_values: tuple[str, str, str] | None = None
        self._styled_status: str | None = None
        super().__init__(classes="tool-call")
        self.refresh_content()

    def on_mount(self) -> None:
        enter_row(self, duration=0.14)

    def compose(self):  # type: ignore[no-untyped-def]
        with Horizontal(classes="tool-call-header"):
            yield self._tool_label

    def set_arguments(self, arguments: Mapping[str, Any] | None, raw: str = "") -> None:
        incoming = dict(arguments or {})
        if incoming:
            self.arguments = incoming
        elif raw:
            self.arguments = {}
        self._apply_activity(take_activity(self.arguments))
        if raw:
            self.raw_arguments = strip_activity_json(raw)
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        incoming = dict(arguments or {})
        if incoming:
            self.arguments = incoming
            self._apply_activity(take_activity(self.arguments))
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
        self.refresh_content()

    def _tool_title(self) -> tuple[str, str]:
        return tool_label(self.tool_name)

    def _summary(self) -> str:
        return tool_detail(self.tool_name, self.arguments, self.raw_arguments)

    def _result_summary(self) -> str:
        return result_preview(self.tool_name, self.result)

    def _refresh_status_class(self) -> None:
        if self._styled_status == self.status:
            return
        if self._styled_status is not None:
            self.remove_class(f"status-{self._styled_status}")
        self.add_class(f"status-{self.status}")
        self._styled_status = self.status

    def _refresh_header(self, label: str, summary: str) -> None:
        target = header_target(summary)
        values = (label, target, self.status)
        if values == self._header_values:
            return
        self._tool_label.update(tool_header_text(label, target, self.status), layout=False)
        self._header_values = values

    def refresh_content(self) -> None:
        label, _icon = self._tool_title()
        self._refresh_header(label, clip_text(self._summary(), self.HEADER_LIMIT))
        self._refresh_status_class()

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


class GenerateImageWidget(ToolCallWidget):
    """Path-oriented generate_image row."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Image", "└")

    def _summary(self) -> str:
        return str(self.arguments.get("path") or self.raw_arguments)

    def _result_summary(self) -> str:
        return generate_image_result(self.result)


class ReadFileWidget(ToolCallWidget):
    """Compact, path-oriented presentation for the read_file tool."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Read", "└")

    def _summary(self) -> str:
        return read_file_detail(self.arguments, self.raw_arguments)

    def _result_summary(self) -> str:
        return read_file_result(self.result)


class BashToolWidget(ToolCallWidget):
    """Bash row: the command gets a wider header than other tools."""

    HEADER_LIMIT = 180


class PatchDiffWidget(ToolCallWidget):
    """Update row with the patched path and +/- line counts."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Update", "±")

    def _patch_path(self) -> str:
        path = str(self.arguments.get("path") or "").strip()
        if path:
            return path
        raw = self.raw_arguments or ""
        match = re.search(r'"path"\s*:\s*"((?:\\.|[^"\\])*)"', raw)
        if match:
            return match.group(1).replace("\\/", "/").replace('\\"', '"')
        match = re.search(
            r"(?:patched|updated|noop:.*in|error:.*?:)\s+(\S+)",
            self.result,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).rstrip(";")
        return ""

    def _summary(self) -> str:
        """Keep live and collected Update rows on the same path-plus-stats line."""
        path = self._patch_path()
        summary = patch_summary(path, self._diff())
        if summary:
            return summary
        return path or header_target(self.raw_arguments)

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._diff_key: tuple[str, str, str] | None = None
        self._diff_cache: list[str] = []
        super().__init__(call_id, tool_name)

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
        self._refresh_header("Update", self._summary())
        self._refresh_status_class()


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


def make_unified_diff(old: str, new: str, path: str) -> list[str]:
    """Build display-ready unified diff lines for an exact-text edit."""
    if not old and not new:
        return []
    lines = list(
        unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    return lines[2:] if len(lines) >= 2 else lines


def diff_stats(diff: list[str]) -> tuple[int, int]:
    """Count additions and deletions in display-ready diff lines."""
    additions = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    deletions = sum(line.startswith("-") and not line.startswith("---") for line in diff)
    return int(additions), int(deletions)


def patch_summary(path: str, diff: list[str]) -> str:
    """Path plus +/− counts for a patch card header."""
    if not diff:
        return path
    additions, deletions = diff_stats(diff)
    stats = f"+{additions} -{deletions}"
    return f"{path} {stats}" if path else stats
