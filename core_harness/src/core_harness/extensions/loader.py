"""Discover and load addon folders from caller-supplied roots.

Every addon is a folder ``<root>/<name>/``. Each one is imported under a
unique module name, its factory (``setup`` by default) is called with an
``ExtensionAPI``, and the result is frozen into an ``ExtensionSnapshot``.
Any failure skips that addon with an ``AddonFailure``; it never raises.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Collection, Iterable

from core_harness.extensions.manifest import AddonManifest, read_manifest
from core_harness.extensions.recorder import AddonRecorder
from core_harness.extensions.registry import AddonFailure, ExtensionSnapshot, LoadedAddon


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _import(manifest: AddonManifest) -> ModuleType:
    safe = "".join(char if char.isalnum() else "_" for char in manifest.name)
    module_name = f"symphony_addon_{safe}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, manifest.entry)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {manifest.entry.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit):
        sys.modules.pop(module_name, None)
        raise
    return module


def _folders(roots: Iterable[Path]) -> list[Path]:
    folders: list[Path] = []
    for root in roots:
        if root.is_dir():
            folders.extend(
                path for path in sorted(root.iterdir())
                if path.is_dir() and not path.name.startswith((".", "_"))
            )
    return folders


def load_addons(
    roots: Iterable[Path],
    *,
    reserved_names: Collection[str] = (),
) -> ExtensionSnapshot:
    """Load every addon under ``roots``. Names in ``reserved_names`` are rejected."""
    loaded: list[LoadedAddon] = []
    failed: list[AddonFailure] = []
    notices: list[str] = []
    seen: set[str] = set()
    for folder in _folders(roots):
        try:
            manifest = read_manifest(folder)
        except Exception as exc:  # noqa: BLE001
            failed.append(AddonFailure(folder.name, "manifest", _error(exc)))
            continue
        if manifest.name in reserved_names:
            message = f"addon {manifest.name!r} uses a built-in name and was not loaded"
            failed.append(AddonFailure(manifest.name, "manifest", message))
            notices.append(message)
            continue
        if manifest.name in seen:
            failed.append(AddonFailure(manifest.name, "manifest", "duplicate addon name"))
            continue
        seen.add(manifest.name)
        try:
            module = _import(manifest)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - addon code is untrusted
            failed.append(AddonFailure(manifest.name, "import", _error(exc)))
            continue
        factory = module.__dict__.get(manifest.factory)
        if not callable(factory):
            failed.append(AddonFailure(manifest.name, "import", f"no callable {manifest.factory}()"))
            continue
        recorder = AddonRecorder()
        try:
            factory(recorder)
        except Exception as exc:  # noqa: BLE001
            failed.append(AddonFailure(manifest.name, "setup", _error(exc)))
            continue
        dispose = module.__dict__.get("dispose")
        loaded.append(LoadedAddon(
            name=manifest.name,
            version=manifest.version,
            root=manifest.root,
            tools=tuple(recorder.tools),
            commands=tuple(recorder.commands),
            subscriptions=tuple(recorder.subscriptions),
            dispose=dispose if callable(dispose) else None,
        ))
    return ExtensionSnapshot(tuple(loaded), tuple(failed), tuple(notices))


__all__ = ["load_addons"]
