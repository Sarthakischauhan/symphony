"""Top bar showing only the current Git branch and selected model."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rich.cells import cell_len
from rich.table import Table
from rich.text import Text
from textual import events
from textual.widgets import Static

from core_ai.providers.catalog import (
    find_provider,
    provider_api_key,
    provider_auth_preference,
    provider_has_oauth,
)
from coding_agent.paths import project_root

CLUSTER_GAP = " " * 4
AUTH_MODEL_GAP = " " * 3
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
    root = project_root(start)
    if root is None:
        return None
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if not marker.is_file():
        return None
    try:
        pointer = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if pointer.startswith("gitdir:"):
        target = Path(pointer.removeprefix("gitdir:").strip())
        return target if target.is_absolute() else root / target
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
        self._auth = ""
        super().__init__(*args, **kwargs)

    def set_context(
        self,
        workspace: Path,
        model: str = "",
        *,
        label: str = "",
        auth: str = "",
    ) -> None:
        branch = read_git_branch(workspace)
        model = model or ""
        if not auth and model:
            provider = find_provider(model.split(":", 1)[0])
            if provider is not None:
                # Provider construction prefers an explicit API key over a
                # stored subscription token, so report the credential actually
                # selected by the runtime.
                preference = provider_auth_preference(provider)
                if preference == "oauth" and provider_has_oauth(provider):
                    auth = "👤 signed in"
                elif provider_api_key(provider):
                    auth = "🔑 API key"
                elif provider_has_oauth(provider):
                    auth = "👤 signed in"
        if branch == self._branch and model == self._model and label == self._label and auth == self._auth:
            return
        self._branch = branch
        self._model = model
        self._label = label
        self._auth = auth
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
        # Budget by terminal cells, not Python len(): emoji badges are one
        # codepoint but two columns, and under-counting cramps/truncates the model.
        right = (
            f"{self._auth}{AUTH_MODEL_GAP}{self._model}"
            if self._auth
            else self._model
        )
        model_width = min(cell_len(right), max(width // 2, 1))
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
            Text(
                right,
                overflow="ellipsis",
                no_wrap=True,
            ),
        )
        return row
