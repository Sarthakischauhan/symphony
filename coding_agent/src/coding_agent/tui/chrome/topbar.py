"""Top bar: `symphony    ~/workspace    branch    model` in muted gray."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.widgets import Static

PRODUCT_LABEL = "symphony"
# Airy spacing between the top-bar clusters (mock uses ~3-4 cells).
CLUSTER_GAP = " " * 4


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
    """Return the checked-out branch for the repository containing `workspace`.

    Reads `.git/HEAD` directly (no subprocess) so the top bar renders instantly
    and works without a `git` binary. A detached HEAD yields a short SHA; a
    directory outside any repository yields an empty string.
    """
    git_dir = _locate_git_dir(workspace.resolve())
    if git_dir is None:
        return ""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        ref = head.removeprefix("ref:").strip()
        return ref.removeprefix("refs/heads/")
    return head[:7]


def _locate_git_dir(start: Path) -> Optional[Path]:
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return marker
        if marker.is_file():
            # Worktrees and submodules store `gitdir: <path>` in a .git file.
            try:
                pointer = marker.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if pointer.startswith("gitdir:"):
                target = Path(pointer.removeprefix("gitdir:").strip())
                if not target.is_absolute():
                    target = candidate / target
                return target
            return None
    return None


def topbar_text(*, workspace: str, branch: str = "", model: str = "") -> Text:
    """Join the non-empty top-bar clusters with the shared airy gap."""
    clusters = [PRODUCT_LABEL, workspace, branch, model]
    return Text(CLUSTER_GAP.join(cluster for cluster in clusters if cluster), no_wrap=True)


class TopBar(Static):
    """Muted single-line header: product, workspace path, git branch, model."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._workspace = ""
        self._branch = ""
        self._model = ""
        super().__init__(*args, **kwargs)

    def set_context(self, workspace: Path, model: str = "") -> None:
        self._workspace = display_workspace_path(workspace)
        self._branch = read_git_branch(workspace)
        self._model = model
        self.update(
            topbar_text(workspace=self._workspace, branch=self._branch, model=self._model)
        )
