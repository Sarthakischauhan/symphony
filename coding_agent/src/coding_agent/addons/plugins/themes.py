"""Read the themes a plugin ships in its ``themes/`` directory. Discovery only.

Two file shapes are accepted, both parsed as data and never executed:

* ``*.json`` in the Claude theme format (``name``, ``base``, ``overrides``), as the
  claude-themes marketplace publishes them.
* ``*.toml`` in Symphony's own ``theme.toml`` shape: a ``[colors]`` table, with an
  optional top-level ``name`` and ``base``.

Turning these into TUI colors is the adapter's job (``coding_agent.tui.theme``);
this module only says which themes exist and what they contain.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coding_agent.extensions import Diagnostic

THEMES_DIRECTORY = "themes"
MAX_THEME_BYTES = 256_000
Base = Literal["dark", "light", "dark-daltonized", "light-daltonized", "dark-ansi", "light-ansi"]
Format = Literal["claude", "symphony"]


class ClaudeThemeFile(BaseModel):
    """The Claude theme schema. Unknown override slots are kept: the adapter ignores what it has no use for."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = ""
    base: Base = "dark"
    overrides: dict[str, str] = Field(default_factory=dict)


class SymphonyThemeFile(BaseModel):
    """A ``theme.toml`` as a plugin ships it: just the palette. CSS stays Symphony's."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    base: Base = "dark"
    colors: dict[str, str]


@dataclass(frozen=True)
class PluginTheme:
    """One theme file of one plugin.

    ``colors`` is the file's own map: slot overrides for a Claude theme, the
    ``[colors]`` table for a Symphony one.
    """

    plugin: str
    name: str
    path: Path
    format: Format
    base: Base
    colors: dict[str, str]

    @property
    def qualified_name(self) -> str:
        """``<plugin>:<Theme Name>``, the name a user picks."""
        return f"{self.plugin}:{self.name}"


def discover_plugin_themes(plugin: str, root: Path) -> tuple[tuple[PluginTheme, ...], tuple[Diagnostic, ...]]:
    """Themes under ``<root>/themes/``, by name. A bad file is a diagnostic; the others still load."""
    directory = root / THEMES_DIRECTORY
    if not directory.is_dir() or directory.is_symlink():
        return (), ()
    found: dict[str, PluginTheme] = {}
    diagnostics: list[Diagnostic] = []
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".json", ".toml"} or not path.is_file() or path.is_symlink():
            continue
        try:
            theme = _read_theme(plugin, path)
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            diagnostics.append(Diagnostic(str(path), f"theme not loaded: {_reason(exc)}"))
            continue
        key = theme.name.casefold()
        if key in found:
            diagnostics.append(Diagnostic(str(path), f"theme {theme.qualified_name!r} is already defined by {found[key].path.name}"))
            continue
        found[key] = theme
    return tuple(sorted(found.values(), key=lambda item: item.name.casefold())), tuple(diagnostics)


def find_theme(themes: tuple[PluginTheme, ...], query: str) -> PluginTheme:
    """Match ``plugin:Name`` or a bare ``Name`` (case-insensitive); an ambiguous bare name is an error."""
    needle = query.strip().casefold()
    exact = [item for item in themes if item.qualified_name.casefold() == needle]
    matches = exact or [item for item in themes if item.name.casefold() == needle]
    if not matches:
        raise ValueError(f"no theme named {query!r}; see: symphony themes list")
    if len(matches) > 1:
        raise ValueError(f"{query!r} is ambiguous: use one of {', '.join(item.qualified_name for item in matches)}")
    return matches[0]


def _read_theme(plugin: str, path: Path) -> PluginTheme:
    if path.stat().st_size > MAX_THEME_BYTES:
        raise ValueError("file is too large")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        claude = ClaudeThemeFile.model_validate(_json_object(text))
        return PluginTheme(plugin, claude.name or _title(path), path, "claude", claude.base, claude.overrides)
    symphony = SymphonyThemeFile.model_validate(_toml_table(text))
    return PluginTheme(plugin, symphony.name or _title(path), path, "symphony", symphony.base, symphony.colors)


def _json_object(text: str) -> dict[str, Any]:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("theme must be a JSON object")
    return raw


def _toml_table(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {exc}") from exc


def _title(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").title()


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(part) for part in error['loc']) or 'theme'}: {error['msg']}" for error in exc.errors())
    return str(exc)


__all__ = ["PluginTheme", "discover_plugin_themes", "find_theme"]
