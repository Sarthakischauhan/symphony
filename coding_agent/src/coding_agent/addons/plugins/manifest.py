"""Read a plugin's manifest in any of the formats plugins ship in.

Looked up in Codex's order, first valid file wins: the portable Agent Plugins
``plugin.json`` at the root, then ``.codex-plugin``, ``.claude-plugin`` and
``.cursor-plugin``. Reading is parsing JSON; no plugin code is touched.

What Symphony can use from a plugin: its skills (``skills`` defaults to
``./skills/``) and, under ``extensions.symphony``, an addon directory. Anything
else the manifest or the plugin tree declares is reported as skipped with a
reason, never silently ignored and never pretended to work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator

from coding_agent.addons.skills.args import fold_whitespace

MANIFEST_PATHS = (
    "plugin.json",
    ".codex-plugin/plugin.json",
    ".claude-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
)
MAX_MANIFEST_BYTES = 256_000
PLUGIN_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
# What a plugin can contribute that Symphony does not load, and why. A key in the
# manifest or a file or directory in the plugin tree each count as a contribution.
UNSUPPORTED: dict[str, str] = {
    "agents": "plugin-defined agents are not supported",
    "commands": "plugin slash commands are not supported",
    "hooks": "hooks are not supported; Symphony runs plugin code only as an addon",
    "automations": "automations are not supported",
    "mcpServers": "MCP servers are not supported yet",
    "apps": "apps are not supported",
    "lspServers": "language servers are not supported",
    "outputStyles": "output styles are not supported",
}
_TREE_MARKERS = {
    "agents": "agents", "commands": "commands", "hooks": "hooks", "automations": "automations",
    "hooks.json": "hooks", ".mcp.json": "mcpServers", "mcp.json": "mcpServers", ".app.json": "apps",
}


class SymphonyExtension(BaseModel):
    """``extensions.symphony``: where the plugin's addons are. Declaring it means the plugin has code."""

    model_config = ConfigDict(extra="forbid")

    addons: str = "addons"

    @field_validator("addons")
    @classmethod
    def _inside_plugin(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("addons must be a relative directory inside the plugin")
        return value


class PluginManifest(BaseModel):
    """The fields every format shares; the rest is ignored (and reported when unsupported)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=PLUGIN_NAME)
    version: str = ""
    description: Annotated[str, AfterValidator(fold_whitespace), Field(max_length=1000)] = ""
    skills: tuple[str, ...] = ("./skills/",)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("skills", mode="before")
    @classmethod
    def _one_or_many(cls, value: Any) -> Any:
        return (value,) if isinstance(value, str) else value

    @field_validator("skills")
    @classmethod
    def _inside_plugin(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            path = Path(item)
            if not item or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"skills path {item!r} must be relative and stay inside the plugin")
        return value

    @property
    def symphony(self) -> SymphonyExtension | None:
        raw = self.extensions.get("symphony")
        return None if raw is None else SymphonyExtension.model_validate(raw)


@dataclass(frozen=True)
class LoadedManifest:
    manifest: PluginManifest
    path: Path
    root: Path
    skipped: tuple[tuple[str, str], ...]


def _unsupported(root: Path, raw: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    found = {key for key in UNSUPPORTED if key in raw}
    found |= {label for marker, label in _TREE_MARKERS.items() if (root / marker).exists()}
    return tuple((label, UNSUPPORTED[label]) for label in UNSUPPORTED if label in found)


def read_manifest(root: Path) -> LoadedManifest:
    """The first manifest under ``root`` that exists and validates; ``ValueError`` if none does."""
    errors: list[str] = []
    for relative in MANIFEST_PATHS:
        path = root / relative
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_MANIFEST_BYTES:
                raise ValueError("manifest is too large")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifest must be a JSON object")
            manifest = PluginManifest.model_validate(raw)
            if manifest.symphony is not None and not (root / manifest.symphony.addons).is_dir():
                raise ValueError(f"extensions.symphony.addons {manifest.symphony.addons!r} is not a directory")
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            errors.append(f"{relative}: {_reason(exc)}")
            continue
        return LoadedManifest(manifest, path, root, _unsupported(root, raw))
    if errors:
        raise ValueError("; ".join(errors))
    raise ValueError("no plugin manifest (looked for " + ", ".join(MANIFEST_PATHS) + ")")


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(part) for part in error['loc']) or 'manifest'}: {error['msg']}" for error in exc.errors())
    return str(exc)


__all__ = ["MANIFEST_PATHS", "UNSUPPORTED", "LoadedManifest", "PluginManifest", "SymphonyExtension", "read_manifest"]
