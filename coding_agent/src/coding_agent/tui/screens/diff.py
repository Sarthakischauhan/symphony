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


_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")


def read_workspace_diff(workspace: Path) -> str:
    """Return the current workspace diff, or a user-facing failure message."""
    try:
        result = subprocess.run(
            # Context is intentional: the modal is a code review surface, not just a
            # change counter. It also makes the line-number gutter useful.
            ["git", "-C", str(workspace), "diff", "--unified=3", "--", "."],
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
    """Render a unified patch with the compact gutter used by the diff modal."""
    # Diff rows must stay on one terminal line. Wrapping long generated source
    # makes continuation rows look like unnumbered diff lines.
    rendered = Text(no_wrap=True, overflow="crop")
    hunks = [match for line in body.splitlines() if (match := _HUNK_RE.match(line))]
    number_width = max(
        2,
        *(len(match.group(1)) for match in hunks),
        *(len(match.group(3)) for match in hunks),
    )
    # A patch can start with a hunk header followed by no context. Keep the
    # gutter stable and reserve one extra column for the change marker.
    old_line = new_line = 0

    for source in body.splitlines():
        match = _HUNK_RE.match(source)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            # Keep the hunk marker aligned with the source below it. The section
            # name is retained because it is useful when scanning a large file.
            rendered.append(" " * (number_width + 5), style="#687e8b")
            rendered.append(source, style="bold #83a9bd")
            rendered.append("\n")
            continue

        if source.startswith("+"):
            line_number = new_line
            new_line += 1
            marker = "+"
            style = "#a8d58d on #19301d"
        elif source.startswith("-"):
            line_number = old_line
            old_line += 1
            marker = "-"
            style = "#e49a9d on #321c20"
        elif source.startswith(" "):
            line_number = new_line
            old_line += 1
            new_line += 1
            marker = " "
            style = "#b8bec1"
        else:
            line_number = 0
            marker = " "
            style = "#737b7f"

        number = str(line_number) if line_number else ""
        gutter = f"{number:>{number_width}} {marker} │ "
        content = source[1:] if source[:1] in {"+", "-", " "} else source
        rendered.append(gutter + content, style=style)
        rendered.append("\n")

    if rendered.plain.endswith("\n"):
        rendered = rendered[:-1]
    return rendered


class DiffFileCard(Container):
    """One changed file with its compact header and patch."""

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
        collapsed = self.has_class("collapsed")
        if collapsed:
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")
        self.query_one(".diff-file-chevron", Static).update("▸" if not collapsed else "▾")
        return not collapsed


class DiffModal(ModalBase[None]):
    """Fullscreen modal for inspecting one changed file at a time."""

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
        self._file_data: list[tuple[str, str]] = []
        self._file_index = 0
        self._cards: list[DiffFileCard] = []

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        self._file_data = split_diff(diff_text)
        path, first_body = self._file_data[0] if self._file_data else ("", "")
        additions, deletions = diff_stats(first_body.splitlines())

        with Container(id="diff-pane", classes="modal-pane"):
            # Keep the left side compact, then use a dedicated spacer to pin the
            # file count and close affordance to the right edge.
            yield Horizontal(
                Static("diff", id="diff-title"),
                Static(path, id="diff-path"),
                Static(
                    Text.assemble(
                        (f"+{additions}", "bold #8fc49a"),
                        ("  ", "#777777"),
                        (f"−{deletions}", "bold #df8b91"),
                    ),
                    id="diff-total-stats",
                ),
                Static("", id="diff-header-spacer"),
                Static(
                    f"1 of {len(self._file_data)} files" if self._file_data else "0 files",
                    id="diff-file-counter",
                ),
                ModalCloseButton("esc  close", id="modal-close"),
                id="diff-header",
            )
            with ModalScroll(id="diff-body", classes="modal-body"):
                if not self._file_data:
                    is_clean = diff_text.strip() in {"", "No local changes found."}
                    yield EmptyState(
                        "Working tree is clean" if is_clean else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                else:
                    for current_path, current_body in self._file_data:
                        card = DiffFileCard(current_path, current_body)
                        self._cards.append(card)
                        yield card
            yield Static(
                "↑↓ scroll    n next file    p previous file    enter collapse    esc close",
                id="diff-hint",
                classes="modal-footer",
            )

    def on_mount(self) -> None:
        if self._cards:
            self._show_file(0, scroll=False)

    def on_key(self, event: events.Key) -> None:
        """Keep modal shortcuts active while the scroll container has focus."""
        actions = {
            "n": self.action_next_file,
            "p": self.action_previous_file,
            "enter": self.action_toggle_collapse,
        }
        action = actions.get(event.key)
        if action is not None:
            event.stop()
            action()

    def _show_file(self, index: int, *, scroll: bool = True) -> None:
        if not self._cards:
            return
        for card in self._cards:
            card.remove_class("selected")
            card.add_class("inactive")
        self._file_index = index % len(self._cards)
        card = self._cards[self._file_index]
        card.remove_class("inactive")
        card.add_class("selected")
        path, body = self._file_data[self._file_index]
        additions, deletions = diff_stats(body.splitlines())
        self.query_one("#diff-path", Static).update(path)
        self.query_one("#diff-file-counter", Static).update(
            f"{self._file_index + 1} of {len(self._cards)} files"
        )
        self.query_one("#diff-total-stats", Static).update(
            Text.assemble(
                (f"+{additions}", "bold #8fc49a"),
                ("  ", "#777777"),
                (f"−{deletions}", "bold #df8b91"),
            )
        )
        if scroll:
            card.scroll_visible(animate=False, top=True)

    def action_next_file(self) -> None:
        if self._cards:
            self._show_file(self._file_index + 1)

    def action_previous_file(self) -> None:
        if self._cards:
            self._show_file(self._file_index - 1)

    def action_toggle_collapse(self) -> None:
        if self._cards:
            self._cards[self._file_index].toggle_collapsed()
