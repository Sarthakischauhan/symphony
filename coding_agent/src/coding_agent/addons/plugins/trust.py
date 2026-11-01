"""What trusting a plugin means.

Trust is permission to run the plugin's addon code, and nothing else: skills
never need it. It is recorded as a digest of the addon directory, so the trust
lapses if a single byte changes, for instance after ``plugins update``.
Trust is not a sandbox; trusted code runs with your permissions.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def addon_digest(addon_root: Path) -> str:
    """SHA-256 over every file's relative path and bytes under ``addon_root``, in sorted order."""
    digest = hashlib.sha256()
    for path in sorted(addon_root.rglob("*")):
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(addon_root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


__all__ = ["addon_digest"]
