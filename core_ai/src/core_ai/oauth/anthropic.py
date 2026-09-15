from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from core_ai.oauth.pkce import extract_callback, generate_pkce, generate_state, reject_state_mismatch
from core_ai.oauth.types import OAuthToken

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPE = "org:create_api_key user:profile user:inference"
OAUTH_BETA = "oauth-2025-04-20"


def looks_like_setup_token(value: str) -> bool:
    raw = value.strip()
    if not raw or "#" in raw or "://" in raw:
        return False
    if raw.startswith("sk-ant-api"):
        return False
    return raw.startswith("sk-ant-oat") or raw.startswith("eyJ") or len(raw) >= 100


def setup_token_from_paste(value: str) -> OAuthToken:
    raw = value.strip()
    if not raw:
        raise ValueError("Paste the token from `claude setup-token`")
    if raw.startswith("sk-ant-api"):
        raise ValueError('That looks like an API key. Choose "Paste API key" instead')
    if not looks_like_setup_token(raw):
        raise ValueError("Expected a setup-token from `claude setup-token`")
    return OAuthToken(access_token=raw, token_type="Bearer")


def build_authorize_url(*, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "code": "true",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def start_anthropic_pkce() -> tuple[str, str, str]:
    verifier, challenge = generate_pkce()
    state = generate_state()
    return build_authorize_url(challenge=challenge, state=state), verifier, state


def exchange_anthropic_code(
    pasted: str,
    *,
    verifier: str,
    expected_state: str = "",
    client: httpx.Client | None = None,
) -> OAuthToken:
    code, state = extract_callback(pasted)
    reject_state_mismatch(state=state, expected_state=expected_state)
    payload = _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "state": state or expected_state,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        client=client,
    )
    token = token_from_response(payload)
    if not token.access_token:
        raise RuntimeError("Anthropic did not return an access token")
    return token


def refresh_anthropic_token(
    token: OAuthToken,
    *,
    client: httpx.Client | None = None,
) -> OAuthToken:
    if not token.refresh_token:
        raise RuntimeError("Anthropic token has no refresh_token")
    payload = _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": token.refresh_token,
        },
        client=client,
    )
    refreshed = token_from_response(payload)
    if not refreshed.refresh_token:
        refreshed.refresh_token = token.refresh_token
    return refreshed


def token_from_response(payload: dict[str, Any]) -> OAuthToken:
    expires_in = int(payload.get("expires_in") or 0)
    return OAuthToken(
        access_token=str(payload.get("access_token") or ""),
        refresh_token=str(payload.get("refresh_token") or ""),
        id_token=str(payload.get("id_token") or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
        expires_at=(time.time() + expires_in) if expires_in else 0.0,
        scope=str(payload.get("scope") or ""),
        raw=payload,
    )


def _post_token(body: dict[str, str], *, client: Optional[httpx.Client]) -> dict[str, Any]:
    own = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        response = http.post(
            TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("error_description") or payload.get("error") or "")
            raise RuntimeError(detail or f"Anthropic token request failed (HTTP {response.status_code})")
        if not isinstance(payload, dict):
            raise RuntimeError("Anthropic token request returned a non-JSON body")
        return payload
    finally:
        if own:
            http.close()
