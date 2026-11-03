"""Marketplace catalogs: a JSON list of plugins and where each one comes from.

Read from ``.agents/plugins/marketplace.json`` (Codex), ``.claude-plugin/marketplace.json``
or ``.cursor-plugin/marketplace.json``, in that order. A plugin's ``source`` is a
relative path (``./plugins/x``), ``{source: local, path}``, ``{source: github, repo}``,
``{source: url|git, url}`` or ``{source: git-subdir, url, path}``, each git form with
an optional ``ref`` and ``sha`` pin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coding_agent.addons.plugins.manifest import PLUGIN_NAME
from coding_agent.extensions.source import GITHUB_BASE, Source

MARKETPLACE_PATHS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".cursor-plugin/marketplace.json",
)
MAX_MARKETPLACE_BYTES = 1_000_000


class SourceSpec(BaseModel):
    """The object form of a plugin source."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source: Literal["local", "path", "github", "url", "git", "git-subdir"]
    path: str = ""
    repo: str = ""
    url: str = ""
    ref: str = ""
    sha: str = ""


class MarketplacePlugin(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=PLUGIN_NAME)
    source: str | SourceSpec
    description: str = ""
    version: str = ""


class MarketplaceManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=PLUGIN_NAME)
    plugins: list[MarketplacePlugin]

    def entry(self, name: str) -> MarketplacePlugin:
        for item in self.plugins:
            if item.name == name:
                return item
        raise ValueError(f"marketplace {self.name!r} has no plugin {name!r}; it lists: {', '.join(i.name for i in self.plugins) or 'nothing'}")


@dataclass(frozen=True)
class PluginOrigin:
    """Where one marketplace entry's plugin comes from, with an optional commit pin."""

    source: Source
    sha: str = ""


def read_marketplace(root: Path) -> MarketplaceManifest:
    errors: list[str] = []
    for relative in MARKETPLACE_PATHS:
        path = root / relative
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_MARKETPLACE_BYTES:
                raise ValueError("marketplace file is too large")
            return MarketplaceManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            errors.append(f"{relative}: {exc}")
    if errors:
        raise ValueError("; ".join(errors))
    raise ValueError("no marketplace file (looked for " + ", ".join(MARKETPLACE_PATHS) + ")")


def plugin_origin(entry: MarketplacePlugin, marketplace_root: Path) -> PluginOrigin:
    """Turn an entry's ``source`` into a concrete source. Relative paths stay inside the marketplace."""
    spec = entry.source
    if isinstance(spec, str):
        return PluginOrigin(_inside(marketplace_root, spec))
    if spec.source in {"local", "path"}:
        return PluginOrigin(_inside(marketplace_root, spec.path))
    if spec.source == "github":
        return PluginOrigin(Source("git", f"{GITHUB_BASE}{spec.repo}.git", spec.ref), spec.sha)
    if not spec.url:
        raise ValueError(f"plugin {entry.name!r}: source {spec.source!r} needs a url")
    subdir = spec.path if spec.source == "git-subdir" else ""
    return PluginOrigin(Source("git", spec.url, spec.ref, subdir), spec.sha)


def _inside(root: Path, relative: str) -> Source:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"plugin path {relative!r} must be relative and stay inside the marketplace")
    return Source("local", str(root), subdir=relative)


__all__ = [
    "MARKETPLACE_PATHS", "MarketplaceManifest", "MarketplacePlugin", "PluginOrigin",
    "plugin_origin", "read_marketplace",
]
