"""Install, switch and roll back the Symphony Web frontend bundle.

The built frontend is not part of the Python package. Each GitHub release
carries ``web-<version>.tar.gz`` and ``web-<version>.tar.gz.sha256``. They are
installed under ``<symphony dir>/web``::

    web/
      0.0.2/          extracted bundle (index.html at the top)
      0.0.1/
      current -> 0.0.2
      previous -> 0.0.1

A download is staged in a hidden temp dir inside ``web/`` (same filesystem),
checked against the published SHA-256, extracted there, and moved into place
with a rename. ``current`` and ``previous`` are symlinks replaced with
``os.replace``, so a reader always sees either the old or the new target.
Only the bundles named by ``current`` and ``previous`` are kept.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath

RELEASES = "https://github.com/Sarthakischauhan/symphony/releases/download"
TIMEOUT_SECONDS = 60.0
CURRENT = "current"
PREVIOUS = "previous"
DIGEST = ".sha256"
INSTALL_HINT = "Run `symphony web --update` (or re-run install.sh) to install the Symphony Web assets."
# A source checkout keeps the frontend next to the Python package.
SOURCE = Path(__file__).resolve().parents[3] / "web-ui"

Fetch = Callable[[str, Path], None]


class BundleError(RuntimeError):
    """A bundle could not be installed, switched or found."""


def bundle_root() -> Path:
    from coding_agent.config import symphony_dir

    return symphony_dir() / "web"


def asset_url(version: str, *, base: str | None = None) -> str:
    releases = base or os.environ.get("SYMPHONY_WEB_RELEASES", "").strip() or RELEASES
    return f"{releases.rstrip('/')}/v{version}/web-{version}.tar.gz"


def download(url: str, dest: Path) -> None:
    """Stream one URL to a file; any network error leaves only the partial temp file."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response, dest.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as exc:
        raise BundleError(f"download failed: {url}: {exc}") from exc


def install(version: str, root: Path, *, fetch: Fetch = download) -> Path:
    """Install one release's bundle and make it current. Returns its directory."""
    if not version or "/" in version or version.startswith(".") or version in {CURRENT, PREVIOUS}:
        raise BundleError(f"invalid version: {version!r}")
    root.mkdir(parents=True, exist_ok=True)
    _clean_staging(root)
    url = asset_url(version)
    stage = root / f".tmp-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        fetch(url + ".sha256", stage / "checksum")
        expected = _expected_digest(stage / "checksum")
        target = root / version
        if (target / DIGEST).is_file() and (target / DIGEST).read_text().strip() == expected:
            return switch(root, version)
        archive = stage / "web.tar.gz"
        fetch(url, archive)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise BundleError(f"checksum mismatch for {url}: expected {expected}, got {actual}")
        extracted = stage / "bundle"
        _extract(archive, extracted)
        if not (extracted / "index.html").is_file():
            raise BundleError(f"{url} has no index.html at its top level")
        (extracted / DIGEST).write_text(expected + "\n")
        if target.exists():
            # Re-installing a version whose files differ: move the old copy into
            # staging first so the rename below cannot hit a non-empty directory.
            target.rename(stage / "replaced")
        extracted.rename(target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return switch(root, version)


def switch(root: Path, version: str) -> Path:
    """Point ``current`` at ``version``, keep the old current as ``previous``, prune."""
    target = root / version
    if not (target / "index.html").is_file():
        raise BundleError(f"no installed bundle for {version} in {root}")
    old = _link_target(root / CURRENT)
    if old != version:
        _point(root, CURRENT, version)
        if old is not None and (root / old).is_dir():
            _point(root, PREVIOUS, old)
    _prune(root)
    return target


def rollback(root: Path) -> str:
    """Swap ``current`` and ``previous``. Returns the version now current."""
    previous = _link_target(root / PREVIOUS)
    if previous is None or not (root / previous / "index.html").is_file():
        raise BundleError(f"no previous Symphony Web bundle to roll back to in {root}")
    switch(root, previous)
    return previous


def resolve_static(root: Path, source: Path = SOURCE, *, build: bool = True) -> Path:
    """Return the directory to serve: the installed bundle, else a source build."""
    current = root / CURRENT
    if (current / "index.html").is_file():
        return current.resolve()
    if (source / "package.json").is_file():
        dist = source / "dist"
        if (dist / "index.html").is_file():
            return dist
        if build:
            npm = shutil.which("npm")
            if npm is None:
                raise BundleError(f"{source} needs npm to build the frontend. {INSTALL_HINT}")
            steps = ([] if (source / "node_modules").is_dir() else [[npm, "ci"]]) + [[npm, "run", "build"]]
            for step in steps:
                if subprocess.run(step, cwd=source, check=False).returncode != 0:
                    raise BundleError(f"`{' '.join(step[1:])}` failed in {source}. {INSTALL_HINT}")
            if (dist / "index.html").is_file():
                return dist
    raise BundleError(f"Symphony Web assets are not installed in {current}. {INSTALL_HINT}")


def _expected_digest(path: Path) -> str:
    fields = path.read_text(errors="replace").split()
    digest = fields[0].lower() if fields else ""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise BundleError("the published checksum is not a SHA-256 digest")
    return digest


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise BundleError(f"unsafe path in bundle: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise BundleError(f"unsupported entry in bundle: {member.name}")
            out = dest.joinpath(*name.parts)
            if member.isdir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise BundleError(f"unreadable entry in bundle: {member.name}")
            with source, out.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def _link_target(link: Path) -> str | None:
    return os.readlink(link) if link.is_symlink() else None


def _point(root: Path, name: str, version: str) -> None:
    staged = root / f".{name}-{uuid.uuid4().hex}"
    staged.symlink_to(version, target_is_directory=True)
    os.replace(staged, root / name)


def _prune(root: Path) -> None:
    keep = {_link_target(root / CURRENT), _link_target(root / PREVIOUS)}
    for entry in root.iterdir():
        if entry.name in {CURRENT, PREVIOUS} or entry.name.startswith(".") or entry.name in keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)


def _clean_staging(root: Path) -> None:
    """Remove temp dirs and links left by an install that was killed."""
    for entry in root.iterdir():
        if entry.name.startswith((".tmp-", f".{CURRENT}-", f".{PREVIOUS}-")):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


__all__ = [
    "BundleError",
    "INSTALL_HINT",
    "asset_url",
    "bundle_root",
    "download",
    "install",
    "resolve_static",
    "rollback",
    "switch",
]
