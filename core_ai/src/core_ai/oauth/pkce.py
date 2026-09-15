from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse


def generate_pkce() -> tuple[str, str]:
    """Return `(verifier, S256 challenge)` suitable for OAuth PKCE."""
    verifier = secrets.token_urlsafe(64)
    if len(verifier) > 128:
        verifier = verifier[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def reject_state_mismatch(*, state: str, expected_state: str) -> None:
    """Reject a missing or mismatched CSRF `state` when one was issued."""
    if expected_state and state != expected_state:
        raise ValueError("OAuth state mismatch")


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def extract_callback(value: str) -> tuple[str, str]:
    """Parse a pasted OAuth callback into `(code, state)`.

    Accepts a full redirect URL, `code#state`, or a bare authorization code.
    """
    raw = value.strip().strip('"').strip("'")
    if not raw:
        raise ValueError("Paste the authorization code from the browser")
    if "://" in raw or raw.startswith("http"):
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment)
        code = (query.get("code") or fragment.get("code") or [""])[0]
        state = (query.get("state") or fragment.get("state") or [""])[0]
        error = (query.get("error") or fragment.get("error") or [""])[0]
        if error:
            description = (query.get("error_description") or [error])[0]
            raise ValueError(description)
        if not code:
            raise ValueError("Redirect URL did not include an authorization code")
        return code, state
    if "#" in raw:
        code, _, state = raw.partition("#")
        if not code.strip():
            raise ValueError("Expected format: code#state")
        return code.strip(), state.strip()
    return raw, ""
