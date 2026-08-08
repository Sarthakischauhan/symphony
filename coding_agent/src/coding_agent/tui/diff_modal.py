"""Modal view for showing the current workspace diff."""

from __future__ import annotations

from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from coding_agent.tui.theme import SYMPHONY_CODE_THEME


def _read_diff(workspace: Path) -> str:
    import subprocess

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


def _split_diff(diff_text: str) -> list[tuple[str, str]]:
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


class DiffModal(ModalScreen[None]):
    """Fullscreen modal for inspecting the current git diff."""

    CSS = """
    DiffModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #diff-pane {
        width: 95%;
        height: 90%;
        padding: 1 2;
        background: #1b1b1b;
        border-left: solid #454545;
    }

    #diff-title {
        height: 1;
        color: #d0d0d0;
        padding-bottom: 1;
    }

    #diff-body {
        width: 100%;
        height: 1fr;
        scrollbar-size: 1 1;
        scrollbar-color: #484848;
        scrollbar-color-hover: #606060;
        scrollbar-background: #1b1b1b;
    }

    .diff-file-name {
        width: 100%;
        height: 2;
        padding: 1 0 0 0;
        color: #d0d0d0;
        text-style: bold;
        background: #202020;
    }

    .diff-file-body {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #diff-hint {
        height: 1;
        color: #767676;
        text-align: right;
        padding-top: 1;
    }
    """

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = _read_diff(self.workspace)
        files = _split_diff(diff_text)
        with Container(id="diff-pane"):
            yield Static("PR / workspace diff", id="diff-title")
            with VerticalScroll(id="diff-body"):
                if not files:
                    yield Static(Text(diff_text, style="#a0a0a0"))
                for path, body in files:
                    yield Label(path, classes="diff-file-name")
                    yield Static(
                        Syntax(
                            body,
                            "diff",
                            theme=SYMPHONY_CODE_THEME,  # type: ignore[arg-type]
                            line_numbers=False,
                        ),
                        classes="diff-file-body",
                    )
            yield Static("Esc to close", id="diff-hint")

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "escape":
            self.dismiss(None)
