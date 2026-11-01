"""Add, list, update and remove marketplaces.

An added marketplace is a staged copy under ``<symphony home>/plugins/marketplaces/<name>/``,
so its relative plugin paths keep working and nothing is read from the original
location again until ``marketplace update``. Adding one fetches files only.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from coding_agent.addons.plugins.marketplace import MarketplaceManifest, read_marketplace
from coding_agent.addons.plugins.state import MarketplaceRecord, load_state, plugins_dir, save_state
from coding_agent.extensions.source import Source, parse_source, stage


def marketplace_root(name: str) -> Path:
    return plugins_dir() / "marketplaces" / name


def _fetch(source: Source) -> tuple[Path, MarketplaceManifest, str, tempfile.TemporaryDirectory[str]]:
    plugins_dir().mkdir(parents=True, exist_ok=True)
    scratch = tempfile.TemporaryDirectory(dir=plugins_dir(), prefix=".staging-")
    try:
        staged = Path(scratch.name) / "marketplace"
        revision = stage(source, staged)
        return staged, read_marketplace(staged), revision, scratch
    except BaseException:
        scratch.cleanup()
        raise


def _install(name: str, staged: Path) -> None:
    target = marketplace_root(name)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), target)


def add_marketplace(text: str, *, cwd: Path) -> tuple[MarketplaceRecord, MarketplaceManifest]:
    """Stage ``text`` (a path, git URL or owner/repo), read its catalog, and record it."""
    source = parse_source(text, cwd=cwd, marketplaces=False)
    staged, manifest, revision, scratch = _fetch(source)
    with scratch:
        state = load_state()
        known = state.marketplaces.get(manifest.name)
        if known is not None and known.source != source:
            raise ValueError(f"a marketplace named {manifest.name!r} is already added from {known.source.describe()}; remove it first")
        _install(manifest.name, staged)
        record = MarketplaceRecord(name=manifest.name, source=source, revision=revision)
        state.marketplaces[manifest.name] = record
        save_state(state)
    return record, manifest


def list_marketplaces() -> list[tuple[MarketplaceRecord, MarketplaceManifest | None]]:
    """Each marketplace with its catalog, or ``None`` when its staged copy cannot be read."""
    listed: list[tuple[MarketplaceRecord, MarketplaceManifest | None]] = []
    for name, record in sorted(load_state().marketplaces.items()):
        try:
            listed.append((record, read_marketplace(marketplace_root(name))))
        except ValueError:
            listed.append((record, None))
    return listed


def update_marketplaces(name: str | None = None) -> list[tuple[str, str]]:
    """Re-fetch one or every marketplace; returns ``(name, outcome)`` pairs."""
    state = load_state()
    if name is not None and name not in state.marketplaces:
        raise ValueError(f"no marketplace named {name!r}; see: symphony plugins marketplace list")
    outcomes: list[tuple[str, str]] = []
    for item in sorted(state.marketplaces.values(), key=lambda record: record.name):
        if name not in {None, item.name}:
            continue
        try:
            staged, manifest, revision, scratch = _fetch(item.source)
            with scratch:
                if manifest.name != item.name:
                    raise ValueError(f"the source now calls itself {manifest.name!r}")
                _install(item.name, staged)
            state.marketplaces[item.name] = item.model_copy(update={"revision": revision})
            outcomes.append((item.name, f"updated · {len(manifest.plugins)} plugins"))
        except ValueError as exc:
            outcomes.append((item.name, f"failed: {exc}"))
    save_state(state)
    return outcomes


def remove_marketplace(name: str) -> int:
    """Forget a marketplace; returns how many installed plugins came from it (they stay installed)."""
    state = load_state()
    if state.marketplaces.pop(name, None) is None:
        raise ValueError(f"no marketplace named {name!r}; see: symphony plugins marketplace list")
    shutil.rmtree(marketplace_root(name), ignore_errors=True)
    save_state(state)
    return sum(1 for record in state.plugins.values() if record.marketplace == name)


__all__ = ["add_marketplace", "list_marketplaces", "marketplace_root", "remove_marketplace", "update_marketplaces"]
