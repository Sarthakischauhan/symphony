"""Top bar showing only the current Git branch and selected model."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rich.table import Table
from rich.text import Text
from textual import events
from textual.widgets import Static

CLUSTER_GAP = " " * 4
BRANCH_ICON = "⎇"


def display_workspace_path(workspace: Path, home: Optional[Path] = None) -> str:
    """Render a workspace path with the home directory collapsed to `~`."""
    home = (home or Path.home()).resolve()
    workspace = workspace.resolve()
    if workspace == home:
        return "~"
    try:
        relative = workspace.relative_to(home)
    except ValueError:
        return str(workspace)
    return f"~/{relative.as_posix()}"


def read_git_branch(workspace: Path) -> str:
    """Return the checked-out branch for the repository containing `workspace`."""
    git_dir = _locate_git_dir(workspace.resolve())
    if git_dir is None:
        return ""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        return head.removeprefix("ref:").strip().removeprefix("refs/heads/")
    return head[:7]


def _locate_git_dir(start: Path) -> Optional[Path]:
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return marker
        if marker.is_file():
            try:
                pointer = marker.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if pointer.startswith("gitdir:"):
                target = Path(pointer.removeprefix("gitdir:").strip())
                return target if target.is_absolute() else candidate / target
            return None
    return None


def topbar_text(*, workspace: str = "", branch: str = "", model: str = "") -> Text:
    """Render only branch and model; workspace remains a compatibility argument."""
    clusters: list[str] = []
    if branch:
        clusters.append(f"{BRANCH_ICON} {branch}")
    if model:
        clusters.append(model)
    return Text(CLUSTER_GAP.join(clusters), no_wrap=True)


class TopBar(Static):
    """Header with the branch on the left and active model on the right."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._branch = ""
        self._model = ""
        self._label = ""
        super().__init__(*args, **kwargs)

    def set_context(
        self,
        workspace: Path,
        model: str = "",
        *,
        label: str = "",
    ) -> None:
        self._branch = read_git_branch(workspace)
        self._model = model or ""
        self._label = label
        self.update(self._render_row(max(self.content_size.width, 1)))

    def on_resize(self, event: events.Resize) -> None:
        """Rebudget both columns whenever the terminal changes width."""
        content_width = max(event.size.width - self.styles.gutter.width, 1)
        self.update(self._render_row(content_width))

    def _render_row(self, width: int) -> Table:
        """Build the row for the widget's current width.

        Both sides are deliberately allowed to ellipsize. Without explicit
        width budgets Rich treats the no-wrap model and branch as indivisible,
        which makes narrow terminals crop the entire header.
        """
        left = self._branch
        if self._label:
            left = (
                f"{left}  ›  subagent  ›  {self._label}"
                if left
                else f"subagent  ›  {self._label}"
            )
        model_width = min(len(self._model), max(width // 2, 1))
        row = Table.grid(expand=True, padding=0)
        row.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        row.add_column(
            justify="right",
            overflow="ellipsis",
            no_wrap=True,
            max_width=model_width,
        )
        branch = Text(
            f"{BRANCH_ICON} {left}" if left else "",
            overflow="ellipsis",
            no_wrap=True,
        )
        row.add_row(
            branch,
            Text(self._model, overflow="ellipsis", no_wrap=True),
        )
        return row
