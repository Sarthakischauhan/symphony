"""Top bar: branch on the left, lab mark and model on the right.

The mark is a single colored glyph. A terminal image widget was tried for the
real SVG and rejected: assigning its image refreshes layout, and doing that
from resize made the whole UI relayout forever, which froze scrolling.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from rich.cells import cell_len
from rich.table import Table
from rich.text import Text
from textual import events
from textual.widgets import Static

from coding_agent.personalities import project_root
from coding_agent.tui.theme import SYMPHONY_COLORS

CLUSTER_GAP = " " * 4
AUTH_MODEL_GAP = " " * 3
BRANCH_ICON = "⎇"

# One glyph in the published Simple Icons brand color (2026-10-06).
# Distinctive marks where a single character can carry the logo; a letter
# otherwise. OpenAI and xAI publish no Simple Icons slug.
PROVIDER_MARKS: dict[str, tuple[str, str]] = {
    "anthropic": ("✶", "#D97757"),
    "claude": ("✶", "#D97757"),
    "openai": ("O", "#10A37F"),
    "gemini": ("✦", "#8E75B2"),
    "google": ("✦", "#8E75B2"),
    "grok": ("X", "#EDEDED"),
    "xai": ("X", "#EDEDED"),
    "ollama": ("O", "#EDEDED"),
    "openrouter": ("R", "#6467F2"),
    "mistral": ("M", "#FA520F"),
    "deepseek": ("D", "#5786FE"),
    "qwen": ("Q", "#6950EF"),
    "huggingface": ("H", "#FFD21E"),
    "vercel": ("V", "#EDEDED"),
    "perplexity": ("P", "#1FB8CD"),
    "local": ("L", "#799e7c"),
}


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


def read_git_dirty(workspace: Path) -> bool:
    """True when the worktree has uncommitted changes. Never raises.

    ``git status`` walks the worktree, so callers on the UI thread should not
    run this on a short interval. The top bar probes it from a thread worker.
    """
    try:
        probe = subprocess.run(
            ["git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(probe.stdout.strip())


def short_model_name(model: str) -> str:
    """Drop the provider prefix so the pill reads like a Claude status line."""
    name = model.split(":", 1)[-1] if model else ""
    return name or model


def provider_key(model: str) -> str:
    """Provider id from a ``provider:model`` string."""
    return model.split(":", 1)[0].lower() if model else ""


def provider_mark(model: str) -> tuple[str, str]:
    """A one-cell lab mark and its brand color for a ``provider:model`` id."""
    provider = provider_key(model)
    if provider in PROVIDER_MARKS:
        return PROVIDER_MARKS[provider]
    letter = provider[:1].upper() if provider else "•"
    return (letter, SYMPHONY_COLORS["accent"])


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
    """Render branch and model; workspace remains a compatibility argument."""
    clusters: list[str] = []
    if branch:
        clusters.append(f"{BRANCH_ICON} {branch}")
    if model:
        clusters.append(short_model_name(model))
    return Text(CLUSTER_GAP.join(clusters), no_wrap=True)


class TopBar(Static):
    """Header with the branch on the left and the lab mark plus model on the right."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._branch = ""
        self._dirty = False
        self._model = ""
        self._label = ""
        self._auth = ""
        self._workspace: Optional[Path] = None
        self._branch_timer = None
        self._dirty_probe = False
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Poll Git's HEAD so checkouts made outside the TUI appear promptly.

        The branch itself is a tiny HEAD read. The dirty mark needs
        ``git status``, which is slow enough to hitch the UI, so that probe
        runs on a thread and only every couple of seconds.
        """
        self._branch_timer = self.set_interval(0.5, self._refresh_branch)
        self._dirty_timer = self.set_interval(2.0, self._schedule_dirty_probe)

    def on_unmount(self) -> None:
        if self._branch_timer is not None:
            self._branch_timer.stop()
            self._branch_timer = None
        dirty_timer = getattr(self, "_dirty_timer", None)
        if dirty_timer is not None:
            dirty_timer.stop()
            self._dirty_timer = None

    def _refresh_branch(self) -> None:
        if self._workspace is None:
            return
        branch = read_git_branch(self._workspace)
        if branch == self._branch:
            return
        self._branch = branch
        if not branch:
            self._dirty = False
        self.update(self._render_row(max(self.content_size.width, 1)))

    def _schedule_dirty_probe(self) -> None:
        """Start one background dirty check. Skip when the last one is running."""
        if self._workspace is None or not self._branch or self._dirty_probe:
            return
        self._dirty_probe = True
        self.run_worker(
            self._probe_dirty,
            name="git-dirty",
            group="git-dirty",
            exclusive=True,
            thread=True,
            exit_on_error=False,
        )

    def _probe_dirty(self) -> None:
        workspace = self._workspace
        dirty = read_git_dirty(workspace) if workspace is not None else False
        self.app.call_from_thread(self._apply_dirty, dirty)

    def _apply_dirty(self, dirty: bool) -> None:
        self._dirty_probe = False
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.update(self._render_row(max(self.content_size.width, 1)))

    def set_context(
        self,
        workspace: Path,
        model: str = "",
        *,
        label: str = "",
        auth: str = "",
    ) -> None:
        self._workspace = workspace
        branch = read_git_branch(workspace)
        model = model or ""
        if (
            branch == self._branch
            and model == self._model
            and label == self._label
            and auth == self._auth
        ):
            return
        self._branch = branch
        self._model = model
        self._label = label
        self._auth = auth
        self.update(self._render_row(max(self.content_size.width, 1)))

    def on_resize(self, event: events.Resize) -> None:
        """Rebudget the model whenever the terminal changes width.

        This only replaces renderable text. It must not refresh layout: a
        layout refresh from resize re-enters this handler and freezes scroll.
        """
        content_width = max(event.size.width - self.styles.gutter.width, 1)
        self.update(self._render_row(content_width))

    def _branch_text(self) -> Text:
        branch_label = self._branch
        if self._label:
            branch_label = (
                f"{branch_label}  ›  {self._label}" if branch_label else self._label
            )
        left = Text(no_wrap=True, overflow="ellipsis")
        if branch_label:
            left.append(f"{BRANCH_ICON} ", style=f"bold {SYMPHONY_COLORS['number']}")
            left.append(branch_label, style=SYMPHONY_COLORS["foreground"])
            if self._dirty:
                left.append(" *", style=f"bold {SYMPHONY_COLORS['number']}")
        return left

    def _model_text(self, width: int) -> Text:
        model = self._model
        if width >= 48:
            model = short_model_name(model)
        right = Text(no_wrap=True, overflow="ellipsis")
        if not model:
            return right
        mark, mark_color = provider_mark(self._model)
        right.append(mark, style=f"bold {mark_color}")
        right.append(" ")
        right.append(model, style=f"bold {SYMPHONY_COLORS['accent']}")
        return right

    def _render_row(self, width: int) -> Table:
        """Text row. Width budgets keep a narrow terminal from cropping the header."""
        row = Table.grid(expand=True, padding=0)
        model = self._model_text(width)
        model_width = min(max(cell_len(model.plain), 1), max(width // 2, 1))
        row.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        row.add_column(
            justify="right",
            overflow="ellipsis",
            no_wrap=True,
            max_width=model_width,
        )
        row.add_row(self._branch_text(), model)
        return row
