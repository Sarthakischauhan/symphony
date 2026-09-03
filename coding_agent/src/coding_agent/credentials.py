"""Global `~/.symphony/.env` helpers for provider API keys."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from core_ai.providers.catalog import ProviderSpec, get_provider

OFFLINE_HINT = "Agent is offline. Run /provider to add an API key."

_ENV_ASSIGN = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<eq>\s*=\s*)(?P<value>.*)$"
)
_NEEDS_QUOTES = re.compile(r"""[\s#"\\']""")
_ENV_FILE_MODE = 0o600


def global_env_path() -> Path:
    """Return `~/.symphony/.env`, expanded and resolved."""
    return (Path.home() / ".symphony" / ".env").expanduser().resolve()


def workspace_env_path(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / ".env"


def load_provider_env(workspace: str | Path) -> None:
    """Load provider keys into the process.

    Precedence is process env > workspace `.env` (if present) >
    `~/.symphony/.env`. Files are merged weakest-first, then applied with
    `setdefault` so already-set process env always wins.
    """
    merged: dict[str, str] = {}
    global_path = global_env_path()
    workspace_path = workspace_env_path(workspace)
    merged.update(_dotenv_entries(global_path))
    if workspace_path.resolve() != global_path:
        merged.update(_dotenv_entries(workspace_path))
    for name, value in merged.items():
        os.environ.setdefault(name, value)


def save_provider_key(provider_id: str, api_key: str) -> ProviderSpec:
    spec = get_provider(provider_id)
    key = api_key.strip()
    if not key:
        raise ValueError(f"{spec.label} API key cannot be empty")
    upsert_dotenv(global_env_path(), {spec.env_key: key})
    os.environ[spec.env_key] = key
    return spec


def upsert_dotenv(path: str | Path, updates: Mapping[str, str]) -> None:
    """Create or update KEY=value lines while preserving comments and other keys."""
    path = Path(path)
    remaining = {name: value for name, value in updates.items() if value}
    lines: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                lines.append(line)
                continue
            match = _ENV_ASSIGN.match(line)
            if match and match.group("name") in remaining:
                lines.append(
                    f"{match.group('prefix')}{match.group('name')}"
                    f"{match.group('eq')}{_quote_env(remaining.pop(match.group('name')))}"
                )
            else:
                lines.append(line)
    else:
        lines.extend(["# Symphony provider credentials", ""])
    if remaining:
        if lines and lines[-1] != "":
            lines.append("")
        for name, value in remaining.items():
            lines.append(f"{name}={_quote_env(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _set_private_mode(path)


def _dotenv_entries(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        name: value
        for name, value in dotenv_values(path).items()
        if name and value is not None
    }


def _set_private_mode(path: Path) -> None:
    try:
        path.chmod(_ENV_FILE_MODE)
    except OSError:
        return


def _quote_env(value: str) -> str:
    if _NEEDS_QUOTES.search(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
