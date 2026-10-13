"""Read one addon folder: ``addon.toml`` or a bare ``addon.py``.

``addon.toml`` keys: ``name``, ``version``, ``entry`` (relative path inside
the folder, default ``addon.py``) and ``factory`` (default ``setup``). The
entry must resolve inside the addon folder: no absolute paths, no ``..``,
and no symlink that leaves the folder.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath

MANIFEST_NAME = "addon.toml"
DEFAULT_ENTRY = "addon.py"
DEFAULT_FACTORY = "setup"


@dataclass(frozen=True)
class AddonManifest:
    name: str
    version: str
    root: Path
    entry: Path
    factory: str


def _text(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{MANIFEST_NAME}: {key} must be a non-empty string")
    return value.strip()


def confined_entry(root: Path, entry: str) -> Path:
    """Resolve ``entry`` under ``root`` or raise ``ValueError``."""
    relative = PurePath(entry)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"entry {entry!r} must be a relative path inside the addon")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(f"entry {entry!r} escapes the addon folder")
    if not path.is_file():
        raise ValueError(f"entry {entry!r} is not a file")
    return path


def read_manifest(folder: Path) -> AddonManifest:
    manifest = folder / MANIFEST_NAME
    data: dict[str, object] = {}
    if manifest.is_file():
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    elif not (folder / DEFAULT_ENTRY).is_file():
        raise ValueError(f"needs {MANIFEST_NAME} or {DEFAULT_ENTRY}")
    name = _text(data, "name", folder.name)
    if not name.replace("-", "_").isidentifier():
        raise ValueError(f"addon name {name!r} must be letters, digits, '_' or '-'")
    factory = _text(data, "factory", DEFAULT_FACTORY)
    if not factory.isidentifier():
        raise ValueError(f"factory {factory!r} is not an identifier")
    return AddonManifest(
        name=name,
        version=_text(data, "version", "0.0.0"),
        root=folder.resolve(),
        entry=confined_entry(folder, _text(data, "entry", DEFAULT_ENTRY)),
        factory=factory,
    )


__all__ = ["AddonManifest", "DEFAULT_ENTRY", "MANIFEST_NAME", "confined_entry", "read_manifest"]
