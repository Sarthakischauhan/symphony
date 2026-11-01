"""Where an extension comes from, and copying it into a staging directory.

A source is a local path, a git URL (``https://…``, ``ssh://…``, ``git@host:…``,
``file://…``) or ``owner/repo`` (GitHub), each with an optional ``@ref``; or
``plugin@marketplace``. Staging only copies files. Nothing from the source is
imported or run, git hooks are disabled, and symlinks are never copied.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GITHUB_BASE = "https://github.com/"
MAX_STAGED_BYTES = 64 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 300
_MARKETPLACE_REF = re.compile(r"^([A-Za-z0-9][\w.-]*)@([A-Za-z0-9][\w.-]*)$")
_GITHUB_SHORTHAND = re.compile(r"^([\w.-]+/[\w.-]+?)(?:\.git)?(?:@([^\s/:]+))?$")
_URL_SCHEMES = ("https://", "http://", "ssh://", "git://", "file://")
_SCP_LIKE = re.compile(r"^[\w.-]+@[\w.-]+:[^\s]+$")


@dataclass(frozen=True)
class Source:
    """A parsed source. ``location`` is an absolute path, a git URL, or a plugin name."""

    kind: Literal["local", "git", "marketplace"]
    location: str
    ref: str = ""
    subdir: str = ""
    marketplace: str = ""

    def describe(self) -> str:
        if self.kind == "marketplace":
            return f"{self.location}@{self.marketplace}"
        text = self.location + (f"@{self.ref}" if self.ref else "")
        return text + (f" ({self.subdir})" if self.subdir else "")


def _split_ref(text: str) -> tuple[str, str]:
    base, separator, ref = text.rpartition("@")
    if separator and ref and "/" not in ref and ":" not in ref and "://" in base:
        return base, ref
    return text, ""


def parse_source(text: str, *, cwd: Path, subdir: str = "", marketplaces: bool = True) -> Source:
    """Classify ``text``. An existing path always wins over the other readings."""
    text = text.strip()
    if not text:
        raise ValueError("a source is required")
    if marketplaces:
        named = _MARKETPLACE_REF.match(text)
        if named and not (cwd / text).exists():
            return Source("marketplace", named.group(1), marketplace=named.group(2), subdir=subdir)
    path = (cwd / Path(text).expanduser()).resolve()
    if path.exists():
        return Source("local", str(path), subdir=subdir)
    if text.startswith(_URL_SCHEMES):
        url, ref = _split_ref(text)
        return Source("git", url, ref, subdir)
    if _SCP_LIKE.match(text):
        return Source("git", text, subdir=subdir)
    shorthand = _GITHUB_SHORTHAND.match(text)
    if shorthand:
        return Source("git", f"{GITHUB_BASE}{shorthand.group(1)}.git", shorthand.group(2) or "", subdir)
    expected = "a path that exists, a git URL, owner/repo" + (", or plugin@marketplace" if marketplaces else "")
    raise ValueError(f"cannot read {text!r} as a source: expected {expected}")


def _git(*args: str, cwd: Path | None = None) -> str:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    command = [
        "git", "-c", "protocol.ext.allow=never", "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false", *args,
    ]
    try:
        done = subprocess.run(
            command, cwd=cwd, env=environment, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"git {args[0]} failed: {exc}") from exc
    if done.returncode:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise ValueError(f"git {args[0]} failed: {detail[-1] if detail else 'unknown error'}")
    return done.stdout.strip()


def _checked_subdir(root: Path, subdir: str) -> Path:
    if not subdir:
        return root
    relative = Path(subdir)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"subdirectory {subdir!r} must be relative and stay inside the source")
    target = (root / relative).resolve()
    if not target.is_dir() or not target.is_relative_to(root.resolve()):
        raise ValueError(f"subdirectory {subdir!r} is not a directory in the source")
    return target


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy regular files and directories only: no ``.git``, no symlinks, bounded size."""
    total = 0
    destination.mkdir(parents=True, exist_ok=True)
    for directory, names, files in os.walk(source):
        names[:] = [name for name in names if name != ".git" and not (Path(directory) / name).is_symlink()]
        target = destination / Path(directory).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            total += path.stat().st_size
            if total > MAX_STAGED_BYTES:
                raise ValueError(f"source is larger than {MAX_STAGED_BYTES // (1024 * 1024)} MB")
            shutil.copy2(path, target / name)


def stage(source: Source, destination: Path, *, sha: str = "") -> str:
    """Copy ``source`` into the empty directory ``destination``; return the git revision or ``""``.

    ``sha`` pins a git source: staging fails if the checked-out commit does not start with it.
    """
    if source.kind == "marketplace":
        raise ValueError("resolve a plugin@marketplace source to its own source before staging")
    if source.kind == "local":
        _copy_tree(_checked_subdir(Path(source.location), source.subdir), destination)
        return ""
    with tempfile.TemporaryDirectory(prefix="symphony-git-") as scratch:
        repo = Path(scratch) / "repo"
        _git("clone", "--quiet", "--", source.location, str(repo))
        wanted = sha or source.ref
        if wanted:
            for candidate in (wanted, f"origin/{wanted}"):
                try:
                    _git("checkout", "--quiet", "--detach", f"{candidate}^{{commit}}", cwd=repo)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"{wanted!r} is not a branch, tag or commit of {source.location}")
        revision = _git("rev-parse", "HEAD", cwd=repo)
        if sha and not revision.startswith(sha):
            raise ValueError(f"expected commit {sha} but found {revision}")
        _copy_tree(_checked_subdir(repo, source.subdir), destination)
        return revision


__all__ = ["GITHUB_BASE", "Source", "parse_source", "stage"]
