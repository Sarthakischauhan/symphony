from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx

from core_ai.oauth.types import OAuthToken

_FILE_MODE = 0o600
_DIR_MODE = 0o700


def oauth_dir() -> Path:
    return (Path.home() / ".symphony" / "oauth").expanduser().resolve()


def token_path(provider_id: str) -> Path:
    safe = "".join(ch for ch in provider_id if ch.isalnum() or ch in "-_")
    if not safe or safe != provider_id:
        raise ValueError(f"Invalid provider id: {provider_id}")
    return oauth_dir() / f"{provider_id}.json"


def token_exists(provider_id: str) -> bool:
    try:
        return token_path(provider_id).is_file()
    except ValueError:
        return False


def load_token(provider_id: str) -> Optional[OAuthToken]:
    path = token_path(provider_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("access_token"):
        return None
    return OAuthToken.from_json(payload)


def save_token(provider_id: str, token: OAuthToken) -> Path:
    if not token.access_token:
        raise ValueError("OAuth token is missing access_token")
    path = token_path(provider_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(_DIR_MODE)
    except OSError:
        pass
    payload = json.dumps(token.to_json(), indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, _FILE_MODE)
    try:
        try:
            os.fchmod(fd, _FILE_MODE)
        except (OSError, AttributeError, NotImplementedError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(payload)
    finally:
        if fd >= 0:
            os.close(fd)
    return path


def delete_token(provider_id: str) -> None:
    path = token_path(provider_id)
    if path.is_file():
        path.unlink()


def load_valid_token(
    provider_id: str,
    *,
    client: httpx.Client | None = None,
) -> Optional[OAuthToken]:
    """Load a stored token, refreshing it when it is close to expiry."""
    token = load_token(provider_id)
    if token is None:
        return None
    if not token.is_expired():
        return token
    if not token.refresh_token:
        return None
    try:
        refreshed = refresh_stored_token(provider_id, token, client=client)
    except Exception:
        return None
    save_token(provider_id, refreshed)
    return refreshed


def refresh_stored_token(
    provider_id: str,
    token: OAuthToken,
    *,
    client: httpx.Client | None = None,
) -> OAuthToken:
    if provider_id == "openai":
        from core_ai.oauth.openai_codex import refresh_codex_token

        return refresh_codex_token(token, client=client)
    if provider_id == "anthropic":
        from core_ai.oauth.anthropic import refresh_anthropic_token

        return refresh_anthropic_token(token, client=client)
    if provider_id == "grok":
        from core_ai.oauth.xai import refresh_xai_token

        return refresh_xai_token(token, client=client)
    raise ValueError(f"No OAuth refresh for provider: {provider_id}")
