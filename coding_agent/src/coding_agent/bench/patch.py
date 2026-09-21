"""Git diff of the workspace from a recorded start ref."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

_EXCLUDE = ("workspace.patch", "result.json", "instruction.md", ".symphony")


def git_head(workspace: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    return ref or None


def workspace_diff(workspace: Path, start_ref: str | None = None) -> str:
    """Unified diff of tracked and untracked files versus ``start_ref`` (default HEAD)."""
    workspace = workspace.resolve()
    ref = start_ref or git_head(workspace)
    if ref is None:
        return ""
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="symphony-bench-index-") as tmp:
        env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")
        read = subprocess.run(
            ["git", "read-tree", ref],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if read.returncode != 0:
            return ""
        subprocess.run(
            ["git", "add", "-A", "--", "."],
            cwd=workspace,
            env=env,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "reset", "-q", "--", *_EXCLUDE],
            cwd=workspace,
            env=env,
            capture_output=True,
            check=False,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--binary", "--no-color"],
            cwd=workspace,
            env=env,
            capture_output=True,
            check=False,
        )
        return diff.stdout.decode("utf-8", errors="replace")


def write_workspace_patch(
    workspace: Path,
    dest: Path | None = None,
    *,
    start_ref: str | None = None,
) -> Path:
    dest = dest or workspace.resolve() / "workspace.patch"
    dest.write_text(workspace_diff(workspace, start_ref), encoding="utf-8")
    return dest
