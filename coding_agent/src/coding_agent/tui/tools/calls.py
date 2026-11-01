"""Tool-call widgets for the coding-agent TUI."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from time import monotonic
from typing import Any, Final, Mapping

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Collapsible, Static

from coding_agent.tools.bash import Stream
from coding_agent.tools.summary import ToolSummary
from coding_agent.tui.tools.activity import strip_activity_json, take_activity
from coding_agent.tui.tools.images import ImageAttachment, ImageModal
from coding_agent.tui.tools.labels import (
    generate_image_result,
    header_target,
    read_file_detail,
    read_file_result,
    result_preview,
    patch_path,
    tool_detail,
    tool_header_text,
    tool_label,
)
from coding_agent.tui.tools.modal import ToolCallModal
from coding_agent.tui.tools.code_view import code_view
from coding_agent.tui.tools.snapshots import LIVE_STATUSES, ToolCallSnapshot
from coding_agent.tui.transcript.messages import (
    SelectableStatic,
    clip_text,
    return_composer_focus,
)

IMAGE_CHIP = "[Image 1]"
# Streamed output lines a running Bash card shows under its header; the
# finished card's expanded body carries the result as before.
LIVE_OUTPUT_TAIL_LINES: Final = 6


class BashToolHeader(Horizontal, can_focus=True):
    """Focusable Bash timeline header that toggles its output."""

    class Toggle(Message):
        pass

    def _on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Toggle())
        self.app.call_after_refresh(return_composer_focus, self)

    def _on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.post_message(self.Toggle())


@dataclass(frozen=True)
class ToolOutcome:
    """Completion fields from a protocol-3 ``tool_execution_completed`` payload."""

    status: str
    duration_ms: int | None = None
    exit_code: int | None = None
    summary: ToolSummary | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ToolOutcome | None":
        """Read the typed fields; ``None`` when the event predates them."""
        status = payload.get("status")
        if not isinstance(status, str):
            return None
        duration = payload.get("duration_ms")
        exit_code = payload.get("exit_code")
        raw = payload.get("summary")
        summary: ToolSummary | None = None
        if isinstance(raw, Mapping):
            summary = ToolSummary(
                lines=_count(raw.get("lines")),
                matches=_count(raw.get("matches")),
                added=_count(raw.get("added")),
                removed=_count(raw.get("removed")),
                start_line=_count(raw.get("start_line")),
            )
        return cls(
            status=status,
            duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            summary=summary,
        )

    @property
    def failed(self) -> bool:
        return self.status in {"error", "cancelled", "timeout"}


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) else None


class ToolCallWidget(Collapsible):
    """A collapsible tool lifecycle card that updates as arguments/results arrive."""

    # Cards (image preview, child transcript, Bash output, patch diff) stay
    # mounted as their own transcript entry instead of becoming a row in an
    # Explored group; either way the widget is mounted once and updated.
    keep_in_transcript = False
    # Set by cards that resolve paths against the workspace (generate_image).
    workspace: Path | None = None

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._body = self._make_body()
        self._tool_label = Static(classes="tool-call-label", markup=False)
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments: dict[str, Any] = {}
        self.raw_arguments = ""
        self.result = ""
        self.status = "preparing"
        self._started_at = monotonic()
        self._duration: float | None = None
        self.exit_code: int | None = None
        self.summary: ToolSummary | None = None
        self.activity_verb = ""
        self.activity_reason = ""
        self.activity_group = ""
        self._body_dirty = True
        self._header_values: tuple[str, str, str] | None = None
        self._styled_status: str | None = None
        super().__init__(
            self._body,
            title=tool_label(tool_name)[0],
            collapsed=True,
            collapsed_symbol="",
            expanded_symbol="",
            classes="tool-call",
        )
        self.refresh_content()

    def _make_body(self) -> Static:
        return SelectableStatic(markup=False)

    def compose(self):  # type: ignore[no-untyped-def]
        # Keep CollapsibleTitle in the DOM for keyboard/accessibility compatibility;
        # the timeline header is the visible control shared by every tool.
        yield self._title
        with BashToolHeader(classes="tool-call-header"):
            yield self._tool_label
        with self.Contents():
            yield self._body

    def on_bash_tool_header_toggle(self, event: BashToolHeader.Toggle) -> None:
        event.stop()
        if self.status in LIVE_STATUSES:
            return
        self.open_detail()

    def open_detail(self) -> None:
        """Open a finished call in a card. Live calls stay in the transcript."""
        if self.status in LIVE_STATUSES:
            return
        self.app.push_screen(ToolCallModal(self))

    def detail_title(self) -> Text:
        label, target, status = self._header_values or (self._tool_title()[0], "", self.status)
        return tool_header_text(label, target, status)

    def detail_rows(self, *, wrap: bool = False) -> list[Any]:
        rows: list[Any] = []
        request = self._summary()
        if request:
            rows.append(Text(request, style="bold #d0d0d0"))
        if self.result:
            if rows:
                rows.append(Text())
            rows.append(code_view(self.result, lexer="text", wrap=wrap))
        return rows

    def detail_plain(self) -> str:
        """Plain command/path and result for the card's copy binding."""
        return "\n\n".join(part for part in (self._summary(), self.result) if part)

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

    def set_arguments(self, arguments: Mapping[str, Any] | None, raw: str = "") -> None:
        incoming = dict(arguments or {})
        if incoming:
            self.arguments = incoming
        elif raw:
            self.arguments = {}
        self._apply_activity(take_activity(self.arguments))
        if raw:
            self.raw_arguments = strip_activity_json(raw)
        self._body_dirty = True
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        incoming = dict(arguments or {})
        if incoming:
            self.arguments = incoming
            self._apply_activity(take_activity(self.arguments))
        self._body_dirty = True
        self.refresh_content()

    def _apply_activity(self, activity: Any) -> None:
        self.activity_verb = activity.verb
        self.activity_reason = activity.reason
        self.activity_group = activity.group

    def set_result(self, result: Any, outcome: ToolOutcome | None = None) -> None:
        """Finish the card. ``outcome`` carries payload fields; without it
        (old sessions) duration and status are derived as before."""
        if outcome is not None and outcome.duration_ms is not None:
            self._duration = outcome.duration_ms / 1000
        elif self._duration is None:
            self._duration = max(0.0, monotonic() - self._started_at)
        if outcome is not None:
            self.status = "failed" if outcome.failed else "done"
            self.exit_code = outcome.exit_code
            self.summary = outcome.summary
        else:
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

    def on_click(self, event: events.Click) -> None:
        if self._open_owner_preview():
            event.stop()

    def _open_owner_preview(self) -> bool:
        node = self.parent
        while node is not None:
            if isinstance(node, GenerateImageWidget):
                return node.open_preview()
            node = node.parent
        return False


class GenerateImageWidget(ToolCallWidget):
    """Path-oriented generate_image card with a clickable `[Image 1]` preview."""

    keep_in_transcript = True

    def __init__(self, call_id: str, tool_name: str, *, workspace: Path | None = None) -> None:
        self.workspace = workspace
        super().__init__(call_id, tool_name)

    def _make_body(self) -> Static:
        return ImageChipBody()

    def _tool_title(self) -> tuple[str, str]:
        return ("Image", "└")

    def _summary(self) -> str:
        return str(self.arguments.get("path") or self.raw_arguments)

    def _result_summary(self) -> str:
        return generate_image_result(self.result)

    def set_result(self, result: Any, outcome: ToolOutcome | None = None) -> None:
        super().set_result(result, outcome)
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
        workspace = self.workspace
        path = str(self.arguments.get("path") or "")
        if workspace is None or not path or self.status == "failed":
            return False
        try:
            root = workspace.resolve()
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
        lines = self.summary["lines"] if self.summary is not None else None
        return read_file_result(self.result, lines)

    def detail_rows(self, *, wrap: bool = False) -> list[Any]:
        rows: list[Any] = [Text(self._summary() or "Read", style="bold #d0d0d0")]
        if self.result:
            rows.append(code_view(self.result, lexer=_lexer_for_path(self._summary()), wrap=wrap))
        return rows


def _lexer_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".json": "json",
        ".md": "markdown",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sh": "bash",
    }.get(suffix, "")


class BashToolWidget(ToolCallWidget):
    """Bash card: the command on one header line and, while it runs, the tail
    of its streamed output; once finished, the collapsible command-and-result
    body. Output chunks and status changes only update text in place."""

    keep_in_transcript = True

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._bash_label = Static(classes="bash-tool-label", markup=False)
        self._tail = Static(classes="bash-tool-tail", markup=False)
        self._tail.display = False
        # A fixed window: new chunks repaint the tail without a layout pass.
        self._tail.styles.height = LIVE_OUTPUT_TAIL_LINES
        self._tail_lines: deque[tuple[Stream, str]] = deque(maxlen=LIVE_OUTPUT_TAIL_LINES)
        self._partial_line = ""
        self._partial_stream: Stream = "stdout"
        super().__init__(call_id, tool_name)
        self.add_class("bash-tool")
        self._body.add_class("bash-tool-body")

    def compose(self):  # type: ignore[no-untyped-def]
        with BashToolHeader(classes="bash-tool-header"):
            yield self._bash_label
        yield self._tail
        yield self._body

    def append_output(self, chunk: str, stream: Stream = "stdout") -> None:
        """Take one streamed output chunk; only the tail's text changes.

        stderr lines render red. A stream switch ends the partial line.
        """
        if self._partial_line and stream != self._partial_stream:
            self._tail_lines.append((self._partial_stream, self._partial_line))
            self._partial_line = ""
        lines = (self._partial_line + chunk).split("\n")
        self._partial_line = lines.pop()
        self._partial_stream = stream
        self._tail_lines.extend((stream, line) for line in lines)
        self._refresh_tail()

    def _live_tail(self) -> list[tuple[Stream, str]]:
        if self.status not in LIVE_STATUSES:
            return []
        lines = list(self._tail_lines)
        if self._partial_line:
            lines.append((self._partial_stream, self._partial_line))
        return lines[-LIVE_OUTPUT_TAIL_LINES:]

    def _refresh_tail(self) -> None:
        lines = self._live_tail()
        if lines:
            tail = Text()
            for index, (stream, line) in enumerate(lines):
                if index:
                    tail.append("\n")
                tail.append(line, style="#d66b73" if stream == "stderr" else "")
            self._tail.update(tail, layout=False)
        if bool(lines) != self._tail.display:
            self._tail.display = bool(lines)

    def detail_rows(self, *, wrap: bool = False) -> list[Any]:
        rows: list[Any] = []
        command = self._summary()
        if command:
            rows.append(code_view(command, lexer="bash", wrap=wrap))
        if self.result:
            if rows:
                rows.append(Text())
            rows.append(code_view(self.result, lexer="text", wrap=wrap))
        return rows

    def refresh_content(self) -> None:
        target = header_target(clip_text(self._summary(), 180))
        facts = " · ".join(
            part
            for part in (
                f"exit {self.exit_code}" if self.exit_code else "",
                f"{self._duration:.1f}s" if self._duration is not None and self.status not in LIVE_STATUSES else "",
            )
            if part
        )
        values = ("Bash", target, f"{self.status} {facts}")
        if values != self._header_values:
            # Facts widen the label once, at completion; tail updates stay layout-free.
            self._bash_label.update(tool_header_text("Bash", target, self.status, facts), layout=bool(facts))
            self._header_values = values
        self._refresh_status_class()
        self._refresh_tail()
        self._refresh_body()


class PatchDiffWidget(ToolCallWidget):
    """Patch card: an Update header with the path and diff stats, expanding to
    the unified diff. Argument and status changes update it in place."""

    keep_in_transcript = True
    MAX_DIFF_LINES = 80

    def _tool_title(self) -> tuple[str, str]:
        return ("Update", "±")

    def _patch_path(self) -> str:
        return patch_path(self.arguments, self.raw_arguments, self.result)

    def _summary(self) -> str:
        """Keep live and collected Update rows on the same path-plus-stats line."""
        path = self._patch_path()
        summary_fields = self.summary
        if summary_fields is not None and summary_fields["added"] is not None and summary_fields["removed"] is not None:
            stats = f"+{summary_fields['added']} -{summary_fields['removed']}"
            return f"{path} {stats}" if path else stats
        summary = patch_summary(path, self._diff())
        if summary:
            return summary
        return path or header_target(self.raw_arguments)

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._diff_key: tuple[str, str, str, int] | None = None
        self._diff_cache: list[str] = []
        super().__init__(call_id, tool_name)
        self.add_class("diff-tool")

    def _diff(self) -> list[str]:
        old = str(self.arguments.get("old_str") or "")
        new = str(self.arguments.get("new_str") or "")
        path = str(self.arguments.get("path") or "file")
        start = self._start_line()
        key = (path, old, new, start)
        if key == self._diff_key:
            return self._diff_cache
        self._diff_key = key
        self._diff_cache = make_unified_diff(old, new, start) if old or new else []
        return self._diff_cache

    def _start_line(self) -> int:
        """File line of the match from the protocol summary; 1 until it arrives."""
        reported = self.summary["start_line"] if self.summary is not None else None
        return reported if reported is not None else 1

    def detail_rows(self, *, wrap: bool = False) -> list[Any]:
        rows = [code_view("\n".join(self._diff()), lexer="diff", wrap=wrap)]
        if self.result:
            rows.append(Text(self.result, style="#626262"))
        return rows

    def _diff_rows(self, *, limit: int, clip_result: bool) -> list[Any]:
        diff = self._diff()
        rows: list[Any] = []
        for line in diff[:limit]:
            if line.startswith("@@"):
                rows.append(Text(line, style="#6688a8"))
            elif line.startswith("+"):
                rows.append(Text(line, style="#8fc49a on #203026"))
            elif line.startswith("-"):
                rows.append(Text(line, style="#df8b91 on #352225"))
            else:
                rows.append(Text(line, style="#686868"))
        if len(diff) > limit:
            rows.append(Text(f"… {len(diff) - limit} diff lines hidden", style="#555555"))
        if self.result:
            result_color = "#d66b73" if self.status == "failed" else "#626262"
            result = clip_text(self.result, 260) if clip_result else self.result
            rows.append(Text(f"└  {result}", style=result_color))
        return rows

    def refresh_content(self) -> None:
        self._refresh_header("Update", self._summary())
        self._refresh_status_class()
        if self.collapsed or not self._body_dirty:
            return
        self._body.update(Group(*self._diff_rows(limit=self.MAX_DIFF_LINES, clip_result=True)))
        self._body_dirty = False


def make_tool_widget(
    call_id: str, tool_name: str, *, workspace: Path | None = None
) -> ToolCallWidget:
    """Build the live card for a tool; ``workspace`` resolves generated-image paths."""
    if tool_name == "spawn_agent":
        from coding_agent.tui.runtime.subagent import SubagentWidget

        return SubagentWidget(call_id, tool_name)
    if tool_name == "bash":
        return BashToolWidget(call_id, tool_name)
    if tool_name == "read_file":
        return ReadFileWidget(call_id, tool_name)
    if tool_name == "generate_image":
        return GenerateImageWidget(call_id, tool_name, workspace=workspace)
    if tool_name == "patch":
        return PatchDiffWidget(call_id, tool_name)
    return ToolCallWidget(call_id, tool_name)


def make_unified_diff(old: str, new: str, start_line: int = 1) -> list[str]:
    """Build display-ready unified diff lines for an exact-text edit.

    Hunks are numbered in file lines: ``start_line`` (where old_str matched in
    the file) is the line number of old_str's first line on both sides.
    """
    if not old and not new:
        return []
    offset = max(start_line, 1) - 1
    a, b = old.splitlines(), new.splitlines()
    lines: list[str] = []
    for group in SequenceMatcher(None, a, b).get_grouped_opcodes(3):
        first, last = group[0], group[-1]
        old_range = _hunk_range(first[1] + offset, last[2] + offset)
        new_range = _hunk_range(first[3] + offset, last[4] + offset)
        lines.append(f"@@ -{old_range} +{new_range} @@")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(" " + line for line in a[i1:i2])
                continue
            if tag in {"replace", "delete"}:
                lines.extend("-" + line for line in a[i1:i2])
            if tag in {"replace", "insert"}:
                lines.extend("+" + line for line in b[j1:j2])
    return lines


def _hunk_range(start: int, stop: int) -> str:
    """A unified-diff range for 0-based ``[start, stop)``, as difflib writes it."""
    length = stop - start
    if length == 1:
        return str(start + 1)
    # A zero-length side names the line before the change.
    return f"{start + 1 if length else start},{length}"


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
