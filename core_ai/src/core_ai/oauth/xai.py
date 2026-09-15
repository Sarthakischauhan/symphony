from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from core_ai.oauth.types import OAuthToken

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
CLI_CHAT_PROXY_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
TOKEN_AUTH_VALUE = "xai-grok-cli"
CLIENT_IDENTIFIER = "symphony"
CLIENT_VERSION = "0.1.0"
FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
}


def grok_cli_request_headers() -> dict[str, str]:
    """Headers the Grok CLI chat proxy expects for SuperGrok session tokens."""
    return {
        "X-XAI-Token-Auth": TOKEN_AUTH_VALUE,
        "x-grok-client-identifier": CLIENT_IDENTIFIER,
        "x-grok-client-version": CLIENT_VERSION,
        "User-Agent": f"{CLIENT_IDENTIFIER}/{CLIENT_VERSION}",
    }


class AuthorizationPending(RuntimeError):
    """RFC 8628: user has not finished authorizing yet."""


class SlowDown(RuntimeError):
    """RFC 8628: caller should increase the poll interval."""


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


def request_device_code(*, client: httpx.Client | None = None) -> DeviceCode:
    payload = _post_form(
        DEVICE_CODE_URL,
        {"client_id": CLIENT_ID, "scope": SCOPE},
        client=client,
        label="xAI device code request",
    )
    device_code = str(payload.get("device_code") or "")
    user_code = str(payload.get("user_code") or "")
    uri = str(payload.get("verification_uri") or "")
    if not device_code or not user_code or not uri:
        raise RuntimeError("xAI device code response was incomplete")
    complete = str(payload.get("verification_uri_complete") or "") or f"{uri.rstrip('/')}/{user_code}"
    interval = int(payload.get("interval") or 5)
    expires_in = int(payload.get("expires_in") or 300)
    return DeviceCode(
        device_code=device_code,
        user_code=user_code,
        verification_uri=uri,
        verification_uri_complete=complete,
        expires_in=max(expires_in, 30),
        interval=max(interval, 1),
    )


def poll_device_token(
    device: DeviceCode,
    *,
    client: httpx.Client | None = None,
) -> OAuthToken:
    payload = _post_form(
        TOKEN_URL,
        {
            "grant_type": DEVICE_GRANT,
            "client_id": CLIENT_ID,
            "device_code": device.device_code,
        },
        client=client,
        label="xAI token poll",
        allow_oauth_errors=True,
    )
    error = str(payload.get("error") or "")
    if error == "authorization_pending":
        raise AuthorizationPending()
    if error == "slow_down":
        raise SlowDown()
    if error in {"access_denied", "authorization_denied"}:
        raise RuntimeError("xAI login was denied")
    if error == "expired_token":
        raise RuntimeError("xAI login expired. Start again from /provider")
    if error:
        raise RuntimeError(str(payload.get("error_description") or error))
    token = token_from_response(payload)
    if not token.access_token:
        raise RuntimeError("xAI did not return an access token")
    return token


def refresh_xai_token(
    token: OAuthToken,
    *,
    client: httpx.Client | None = None,
) -> OAuthToken:
    if not token.refresh_token:
        raise RuntimeError("xAI token has no refresh_token")
    payload = _post_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": token.refresh_token,
        },
        client=client,
        label="xAI token refresh",
    )
    refreshed = token_from_response(payload)
    if not refreshed.refresh_token:
        refreshed.refresh_token = token.refresh_token
    if not refreshed.access_token:
        raise RuntimeError("xAI did not return an access token")
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


def _post_form(
    url: str,
    data: dict[str, str],
    *,
    client: Optional[httpx.Client],
    label: str,
    allow_oauth_errors: bool = False,
) -> dict[str, Any]:
    own = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        response = http.post(url, data=data, headers=FORM_HEADERS)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            error = ""
            if isinstance(payload, dict):
                error = str(payload.get("error") or "")
                if allow_oauth_errors and error in {
                    "authorization_pending",
                    "slow_down",
                    "access_denied",
                    "authorization_denied",
                    "expired_token",
                }:
                    return payload
                detail = str(payload.get("error_description") or error)
            else:
                detail = ""
            raise RuntimeError(detail or f"{label} failed (HTTP {response.status_code})")
        if not isinstance(payload, dict):
            raise RuntimeError(f"{label} returned a non-JSON body")
        return payload
    finally:
        if own:
            http.close()
