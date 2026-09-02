"""Workspace `.env` helpers for provider API keys."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

from core_ai.providers.catalog import ProviderSpec, get_provider

OFFLINE_HINT = "Agent is offline. Run /provider to add an API key."

_ENV_ASSIGN = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<eq>\s*=\s*)(?P<value>.*)$"
)
_NEEDS_QUOTES = re.compile(r"""[\s#"\\']""")


def workspace_env_path(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / ".env"


def load_provider_env(workspace: str | Path) -> None:
    """Load cwd `.env`, then workspace `.env` so spawn keys win."""
    cwd_env = Path.cwd() / ".env"
    env_path = workspace_env_path(workspace)
    if cwd_env.exists() and cwd_env.resolve() != env_path.resolve():
        load_dotenv(cwd_env, override=False)
    if env_path.exists():
        load_dotenv(env_path, override=True)



def save_provider_key(workspace: str | Path, provider_id: str, api_key: str) -> ProviderSpec:
    spec = get_provider(provider_id)
    key = api_key.strip()
    if not key:
        raise ValueError(f"{spec.label} API key cannot be empty")
    upsert_dotenv(workspace_env_path(workspace), {spec.env_key: key})
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


def _quote_env(value: str) -> str:
    if _NEEDS_QUOTES.search(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
