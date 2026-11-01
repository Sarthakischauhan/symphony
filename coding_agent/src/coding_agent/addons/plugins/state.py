"""What is installed and enabled, in ``<symphony home>/plugins/state.json``.

Only this module writes the file. Enabling a plugin is what lets its addon load.
Layout of ``<symphony home>/plugins/``: ``state.json``, ``marketplaces/<name>/``
(a copy of each added marketplace) and ``cache/<marketplace>/<plugin>/<version>/``
(the installed plugins).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from coding_agent.config import symphony_dir
from coding_agent.extensions.source import Source

STATE_VERSION = 1


def plugins_dir() -> Path:
    return symphony_dir() / "plugins"


class PluginRecord(BaseModel):
    """One plugin the user acted on.

    ``installed`` plugins live in the cache and carry the ``source`` they came from.
    Others are plugin directories found in place (a project's ``.symphony/plugins/x``)
    that were enabled or disabled by hand.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    marketplace: str = ""
    version: str = ""
    revision: str = ""
    source: Source | None = None
    via: str = ""
    path: str = ""
    installed: bool = False
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.name}@{self.marketplace}"


class MarketplaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: Source
    revision: str = ""


class PluginState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = STATE_VERSION
    plugins: dict[str, PluginRecord] = Field(default_factory=dict)
    marketplaces: dict[str, MarketplaceRecord] = Field(default_factory=dict)


def load_state() -> PluginState:
    path = plugins_dir() / "state.json"
    if not path.is_file():
        return PluginState()
    try:
        return PluginState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is unreadable ({exc}); fix or delete it") from exc


def save_state(state: PluginState) -> None:
    """Write atomically so a crash never leaves half a file."""
    directory = plugins_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = state.model_dump(mode="json")
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, directory / "state.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


__all__ = ["MarketplaceRecord", "PluginRecord", "PluginState", "load_state", "plugins_dir", "save_state"]
