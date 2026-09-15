from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from core_ai.oauth.pkce import (
    decode_jwt_payload,
    extract_callback,
    generate_pkce,
    generate_state,
    reject_state_mismatch,
)
from core_ai.oauth.types import OAuthToken

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
SCOPE = "openid profile email offline_access"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
ORIGINATOR = "symphony"
JWT_AUTH_CLAIM = "https://api.openai.com/auth"


def is_codex_base_url(value: str) -> bool:
    """True when `value` is the ChatGPT Codex Responses host."""
    normalized = (value or "").strip().rstrip("/").lower()
    return "/backend-api/codex" in normalized


def require_chatgpt_account_id(token: OAuthToken) -> str:
    """Return the ChatGPT account id, extracting it from JWTs when needed."""
    account_id = (token.account_id or "").strip() or chatgpt_account_id(
        token.access_token, token.id_token
    )
    if not account_id:
        raise RuntimeError(
            "ChatGPT login did not include an account id; ChatGPT-Account-Id is required"
        )
    token.account_id = account_id
    return account_id


def chatgpt_account_id(*tokens: str) -> str:
    for token in tokens:
        if not token:
            continue
        payload = decode_jwt_payload(token)
        auth = payload.get(JWT_AUTH_CLAIM)
        if isinstance(auth, dict):
            account = str(auth.get("chatgpt_account_id") or "")
            if account:
                return account
        account = str(payload.get("chatgpt_account_id") or "")
        if account:
            return account
    return ""


def token_from_response(payload: dict[str, Any], *, account_id: str = "") -> OAuthToken:
    access = str(payload.get("access_token") or "")
    id_token = str(payload.get("id_token") or "")
    expires_in = int(payload.get("expires_in") or 0)
    resolved = account_id or chatgpt_account_id(access, id_token)
    return OAuthToken(
        access_token=access,
        refresh_token=str(payload.get("refresh_token") or ""),
        id_token=id_token,
        token_type=str(payload.get("token_type") or "Bearer"),
        expires_at=(time.time() + expires_in) if expires_in else 0.0,
        account_id=resolved,
        scope=str(payload.get("scope") or ""),
        raw=payload,
    )


def build_authorize_url(*, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": ORIGINATOR,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def start_codex_pkce() -> tuple[str, str, str]:
    """Return `(authorize_url, verifier, state)`."""
    verifier, challenge = generate_pkce()
    state = generate_state()
    return build_authorize_url(challenge=challenge, state=state), verifier, state


def exchange_codex_code(
    code: str,
    *,
    verifier: str,
    state: str = "",
    expected_state: str = "",
    client: httpx.Client | None = None,
) -> OAuthToken:
    reject_state_mismatch(state=state, expected_state=expected_state)
    payload = _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        client=client,
    )
    token = token_from_response(payload)
    if not token.access_token:
        raise RuntimeError("OpenAI did not return an access token")
    require_chatgpt_account_id(token)
    return token


def refresh_codex_token(
    token: OAuthToken,
    *,
    client: httpx.Client | None = None,
) -> OAuthToken:
    if not token.refresh_token:
        raise RuntimeError("OpenAI token has no refresh_token")
    payload = _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": token.refresh_token,
        },
        client=client,
    )
    refreshed = token_from_response(payload, account_id=token.account_id)
    if not refreshed.refresh_token:
        refreshed.refresh_token = token.refresh_token
    if not refreshed.account_id:
        refreshed.account_id = token.account_id
    require_chatgpt_account_id(refreshed)
    return refreshed


def parse_codex_callback(value: str) -> tuple[str, str]:
    return extract_callback(value)


def codex_request_headers(token: OAuthToken) -> dict[str, str]:
    return {
        "OpenAI-Beta": "responses=experimental",
        "originator": ORIGINATOR,
        "ChatGPT-Account-Id": require_chatgpt_account_id(token),
    }


def _post_token(data: dict[str, str], *, client: Optional[httpx.Client]) -> dict[str, Any]:
    own = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        response = http.post(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        return _json_or_error(response, "OpenAI token request")
    finally:
        if own:
            http.close()


def _json_or_error(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error_description") or payload.get("error") or "")
        raise RuntimeError(detail or f"{label} failed (HTTP {response.status_code})")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned a non-JSON body")
    return payload
