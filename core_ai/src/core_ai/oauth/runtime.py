from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from core_ai.oauth.anthropic import OAUTH_BETA
from core_ai.oauth.openai_codex import CODEX_BASE_URL, codex_request_headers
from core_ai.oauth.store import load_token, load_valid_token, refresh_stored_token, save_token
from core_ai.oauth.types import OAuthToken
from core_ai.oauth.xai import CLI_CHAT_PROXY_BASE_URL, grok_cli_request_headers


@dataclass
class OAuthRuntime:
    """Resolved subscription credentials used to construct a provider."""

    token: OAuthToken
    api_key: str
    base_url: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    use_bearer: bool = True


def refresh_oauth_credentials(provider_id: str) -> dict[str, Any] | None:
    """Force-refresh a stored OAuth token after the provider rejected it.

    ``load_valid_token`` only refreshes near expiry. The Grok CLI proxy can
    reject a bearer that still looks unexpired (``PermissionDenied`` / ``no
    auth context``), so the live request path calls this once and retries
    with the replacement access token.
    """
    token = load_token(provider_id)
    if token is None or not token.refresh_token:
        return None
    try:
        refreshed = refresh_stored_token(provider_id, token)
    except Exception:
        return None
    if not refreshed.access_token or refreshed.access_token == token.access_token:
        return None
    save_token(provider_id, refreshed)
    runtime = _runtime_from_token(provider_id, refreshed)
    if runtime is None:
        return None
    return {
        "api_key": runtime.api_key,
        "base_url": runtime.base_url,
        "extra_headers": runtime.extra_headers,
    }


def oauth_runtime_for(
    provider_id: str,
    *,
    client: httpx.Client | None = None,
) -> OAuthRuntime | None:
    token = load_valid_token(provider_id, client=client)
    if token is None or not token.access_token:
        return None
    return _runtime_from_token(provider_id, token)


def _runtime_from_token(provider_id: str, token: OAuthToken) -> OAuthRuntime | None:
    if provider_id == "openai":
        return OAuthRuntime(
            token=token,
            api_key=token.access_token,
            base_url=CODEX_BASE_URL,
            extra_headers=codex_request_headers(token),
            use_bearer=True,
        )
    if provider_id == "anthropic":
        return OAuthRuntime(
            token=token,
            api_key=token.access_token,
            extra_headers={"anthropic-beta": OAUTH_BETA},
            use_bearer=True,
        )
    if provider_id == "grok":
        return OAuthRuntime(
            token=token,
            api_key=token.access_token,
            base_url=CLI_CHAT_PROXY_BASE_URL,
            extra_headers=grok_cli_request_headers(),
            use_bearer=True,
        )
    return None
