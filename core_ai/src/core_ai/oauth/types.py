from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


class LoginCancelled(RuntimeError):
    """Raised when the user dismisses an in-progress OAuth login."""

    def __init__(self) -> None:
        super().__init__("Login cancelled")


@dataclass
class OAuthToken:
    """Persisted OAuth (or setup-token) credentials for one provider."""

    access_token: str
    refresh_token: str = ""
    id_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0
    account_id: str = ""
    scope: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, skew: float = 60.0) -> bool:
        if not self.expires_at:
            return False
        return time.time() >= (self.expires_at - skew)

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "account_id": self.account_id,
            "scope": self.scope,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> OAuthToken:
        return cls(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            id_token=str(payload.get("id_token") or ""),
            token_type=str(payload.get("token_type") or "Bearer"),
            expires_at=float(payload.get("expires_at") or 0),
            account_id=str(payload.get("account_id") or ""),
            scope=str(payload.get("scope") or ""),
            raw=payload,
        )


@dataclass
class LoginPrompt:
    """Copy the TUI shows while a login is in flight."""

    provider_id: str
    kind: Literal["browser", "device", "paste"]
    title: str
    instructions: str
    url: str = ""
    user_code: str = ""
    paste_hint: str = ""


OAUTH_PROVIDER_IDS = frozenset({"openai", "anthropic", "grok"})


def supports_oauth(provider_id: str) -> bool:
    return provider_id in OAUTH_PROVIDER_IDS
