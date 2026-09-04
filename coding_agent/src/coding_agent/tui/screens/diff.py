"""Workspace diff modal screen."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import DIFF_MODAL_CSS
from coding_agent.tui.tools.diff import diff_stats


_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def read_workspace_diff(workspace: Path) -> str:
    """Return the current workspace diff, or a user-facing failure message."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--unified=0", "--", "."],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to run git diff: {exc}"

    output = (result.stdout or "").strip()
    if output:
        return output
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        return err or "git diff failed"
    return "No local changes found."


def split_diff(diff_text: str) -> list[tuple[str, str]]:
    """Split a Git diff into a path and body for each changed file."""
    files: list[tuple[str, str]] = []
    path = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if path:
                files.append((path, "\n".join(lines)))
            paths = line.removeprefix("diff --git ")
            path = paths.split(" b/", 1)[-1].removeprefix("b/")
            lines = []
        elif line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file")):
            continue
        elif path:
            lines.append(line)

    if path:
        files.append((path, "\n".join(lines)))
    return files


def _numbered_diff(body: str) -> Text:
    """Render a patch with old/new line numbers and a colored change gutter."""
    rendered = Text()
    old_line = new_line = 0
    old_width = new_width = 1

    # Determine widths from all hunk headers so the gutter doesn't jump between hunks.
    for line in body.splitlines():
        match = _HUNK_RE.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            old_width = max(old_width, len(match.group(1)))
            new_width = max(new_width, len(match.group(3)))

    old_line = new_line = 0
    for source in body.splitlines():
        match = _HUNK_RE.match(source)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            rendered.append(f"{'':>{old_width}} {'':>{new_width}}   ")
            rendered.append(source, style="bold #83a9bd")
            rendered.append("\n")
            continue

        if source.startswith("+"):
            old_number, new_number = "", str(new_line)
            new_line += 1
            style = "#a8d58d on #19301d"
            marker = "+"
        elif source.startswith("-"):
            old_number, new_number = str(old_line), ""
            old_line += 1
            style = "#e49a9d on #321c20"
            marker = "-"
        elif source.startswith(" "):
            old_number, new_number = str(old_line), str(new_line)
            old_line += 1
            new_line += 1
            style = "#b8bec1"
            marker = " "
        else:
            # Metadata such as a no-newline marker is useful, but has no line number.
            old_number = new_number = ""
            style = "#737b7f"
            marker = " "

        gutter = (
            f"{old_number:>{old_width}} {new_number:>{new_width}} {marker} "
        )
        rendered.append(
            gutter + source[1:] if source[:1] in {"+", "-", " "} else gutter + source,
            style=style,
        )
        rendered.append("\n")

    if rendered.plain.endswith("\n"):
        rendered = rendered[:-1]
    return rendered


class DiffFileCard(Container):
    """One changed file with a clear header, stats, and numbered patch."""

    def __init__(self, path: str, body: str) -> None:
        self.path = path
        self.body = body
        self.additions, self.deletions = diff_stats(body.splitlines())
        super().__init__(classes="diff-file-card")

    def compose(self):  # type: ignore[no-untyped-def]
        stats = Text()
        stats.append(f"+{self.additions}", style="bold #8fc49a")
        stats.append(f"  −{self.deletions}", style="bold #df8b91")
        with Horizontal(classes="diff-file-header"):
            yield Static("▾", classes="diff-file-chevron")
            yield Static(Text(self.path, style="bold #d0d0d0"), classes="diff-file-path")
            yield Static(stats, classes="diff-file-stats")
        yield Static(_numbered_diff(self.body), classes="diff-patch", markup=False)

    def toggle_collapsed(self) -> bool:
        """Toggle this card and return whether it is now collapsed."""
        collapsed = self.toggle_class("collapsed")
        self.query_one(".diff-file-chevron", Static).update("▸" if collapsed else "▾")
        return collapsed


class DiffModal(ModalBase[None]):
    """Fullscreen modal for inspecting the current git diff."""

    CSS = DIFF_MODAL_CSS
    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
        Binding("n", "next_file", "Next file", show=False, priority=True),
        Binding("p", "previous_file", "Previous file", show=False, priority=True),
        Binding("enter", "toggle_collapse", "Collapse", show=False, priority=True),
    ]

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._files: list[DiffFileCard] = []
        self._file_index = 0

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        files = split_diff(diff_text)
        total_additions = sum(diff_stats(body.splitlines())[0] for _path, body in files)
        total_deletions = sum(diff_stats(body.splitlines())[1] for _path, body in files)
        with Container(id="diff-pane", classes="modal-pane"):
            with Horizontal(id="diff-header"):
                yield Static("diff", id="diff-title")
                yield Static("", id="diff-path")
                yield Static(
                    Text.assemble(
                        (f"+{total_additions}", "bold #8fc49a"),
                        ("  ", "#777777"),
                        (f"−{total_deletions}", "bold #df8b91"),
                    ),
                    id="diff-total-stats",
                )
                yield Static(f"1 of {len(files)} files", id="diff-file-counter")
                yield ModalCloseButton("esc  close", id="modal-close")
            with ModalScroll(id="diff-body", classes="modal-body"):
                if not files:
                    is_clean = diff_text.strip() in {"", "No local changes found."}
                    yield EmptyState(
                        "Working tree is clean" if is_clean else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                for path, body in files:
                    card = DiffFileCard(path, body)
                    self._files.append(card)
                    yield card
            yield Static(
                "↑↓ scroll    n next file    p previous file    enter collapse    esc close",
                id="diff-hint",
                classes="modal-footer",
            )

    def on_mount(self) -> None:
        if self._files:
            self._files[0].add_class("selected")
            self._update_header()

    def on_key(self, event: events.Key) -> None:
        """Handle controls at the modal level even when the scroll view has focus."""
        actions = {"n": self.action_next_file, "p": self.action_previous_file, "enter": self.action_toggle_collapse}
        action = actions.get(event.key)
        if action is not None:
            event.stop()
            action()

    def _update_header(self) -> None:
        if not self._files:
            return
        self.query_one("#diff-file-counter", Static).update(
            f"{self._file_index + 1} of {len(self._files)} files"
        )
        self.query_one("#diff-path", Static).update(self._files[self._file_index].path)

    def _select_file(self, index: int) -> None:
        if not self._files:
            return
        self._files[self._file_index].remove_class("selected")
        self._file_index = index
        card = self._files[self._file_index]
        card.add_class("selected")
        card.scroll_visible(animate=False, top=True)
        self._update_header()

    def action_next_file(self) -> None:
        if self._files:
            self._select_file(min(self._file_index + 1, len(self._files) - 1))

    def action_previous_file(self) -> None:
        if self._files:
            self._select_file(max(self._file_index - 1, 0))

    def action_toggle_collapse(self) -> None:
        if self._files:
            card = self._files[self._file_index]
            card.toggle_collapsed()
            self.set_focus(card)
