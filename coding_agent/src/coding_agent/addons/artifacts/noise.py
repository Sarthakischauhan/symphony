"""Files that match an artifact suffix but are project plumbing, not output.

Auto-capture skips them; ``save_artifact`` still keeps any of them on request.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

# Any path through one of these folders is dependencies, VCS data or build output.
NOISE_DIRS = frozenset({
    "node_modules", ".git", "dist", "build", ".vite", ".next", ".nuxt", ".output",
})
# A folder holding one of these is an application project. Its index.html is the
# dev server entry (Vite, Next, Astro), not a page the run produced.
APP_MARKERS = frozenset({
    "package.json", "vite.config.js", "vite.config.ts", "vite.config.mjs",
    "next.config.js", "next.config.ts", "next.config.mjs", "astro.config.mjs",
    "astro.config.ts",
})
MANIFEST_NAMES = frozenset({"package.json", "package-lock.json", "npm-shrinkwrap.json"})
CONFIG_PATTERNS = ("tsconfig*.json", "*.config.json")
# Lockfiles of every package manager: yarn.lock, Cargo.lock, uv.lock,
# pnpm-lock.yaml, bun.lock(b), deno.lock, *.lock.json, ...
LOCK_PATTERNS = ("*.lock", "*.lockb", "*-lock.json", "*-lock.yaml", "*.lock.json", "*-lock.yml")
GIT_TIMEOUT_SECONDS = 5


def is_noise(path: Path, workspace: Path) -> bool:
    """A manifest, config or lockfile, or anything under a noise folder."""
    parts = path.relative_to(workspace).parts if path.is_relative_to(workspace) else path.parts
    if any(part in NOISE_DIRS for part in parts[:-1]):
        return True
    name = path.name.lower()
    if name in MANIFEST_NAMES:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in (*CONFIG_PATTERNS, *LOCK_PATTERNS))


def is_app_project(folder: Path) -> bool:
    """True when ``folder`` is a web app project rather than a generated site."""
    return any((folder / name).is_file() for name in APP_MARKERS)


def git_tracked(path: Path) -> bool:
    """Whether git tracks ``path`` in the repository that contains it."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "ls-files", "--error-unmatch", "--", path.name],
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # No git, or a hung repository: nothing proves the file is tracked.
        return False
    return result.returncode == 0


__all__ = ["APP_MARKERS", "NOISE_DIRS", "git_tracked", "is_app_project", "is_noise"]
