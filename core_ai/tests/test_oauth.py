from __future__ import annotations

import json
import os
import stat
import time

import httpx
import pytest

from core_ai.oauth.anthropic import (
    exchange_anthropic_code,
    looks_like_setup_token,
    setup_token_from_paste,
)
from core_ai.oauth.login import start_login
from core_ai.oauth.openai_codex import (
    CODEX_BASE_URL,
    chatgpt_account_id,
    exchange_codex_code,
    token_from_response,
)
from core_ai.oauth.pkce import extract_callback, generate_pkce
from core_ai.oauth.runtime import oauth_runtime_for
from core_ai.oauth.store import load_token, load_valid_token, save_token, token_path
from core_ai.oauth.types import OAuthToken
from core_ai.oauth.xai import AuthorizationPending, poll_device_token, request_device_code
from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.catalog import configured_provider_ids, provider_is_configured, get_provider
from core_ai.providers.defaults import build_default_registry
from core_ai.providers.openai import OpenAIProvider


PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "SYMPHONY_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_ENABLED",
    "OLLAMA_MODEL",
    "LOCAL_API_KEY",
    "LOCAL_BASE_URL",
    "LOCAL_MODEL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "GEMINI_BASE_URL",
    "XAI_BASE_URL",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("ascii")
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_extract_callback_url_and_code_state() -> None:
    code, state = extract_callback("http://localhost:1455/auth/callback?code=abc&state=xyz")
    assert (code, state) == ("abc", "xyz")
    code, state = extract_callback("def#ghi")
    assert (code, state) == ("def", "ghi")
    code, state = extract_callback("bare-code")
    assert (code, state) == ("bare-code", "")
    with pytest.raises(ValueError, match="access_denied"):
        extract_callback("http://localhost:1455/auth/callback?error=access_denied")


def test_generate_pkce_s256_shape() -> None:
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43


def test_chatgpt_account_id_from_jwt() -> None:
    payload = {
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct_live"},
    }
    token = f"hdr.{_b64url(payload)}.sig"
    assert chatgpt_account_id(token) == "acct_live"


def test_oauth_store_roundtrip_and_mode() -> None:
    token = OAuthToken(access_token="tok", refresh_token="ref", account_id="acct")
    path = save_token("openai", token)
    assert path == token_path("openai")
    loaded = load_token("openai")
    assert loaded is not None
    assert loaded.access_token == "tok"
    assert loaded.account_id == "acct"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_load_valid_token_refreshes_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    expired = OAuthToken(
        access_token="old",
        refresh_token="ref",
        expires_at=time.time() - 10,
        account_id="acct",
    )
    save_token("openai", expired)

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            200,
            json={"access_token": "new", "refresh_token": "ref2", "expires_in": 3600},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    loaded = load_valid_token("openai", client=client)
    assert loaded is not None
    assert loaded.access_token == "new"
    assert load_token("openai").access_token == "new"  # type: ignore[union-attr]


def test_setup_token_and_rejects_api_key() -> None:
    token = setup_token_from_paste("sk-ant-oat-abcdef")
    assert token.access_token == "sk-ant-oat-abcdef"
    assert looks_like_setup_token("sk-ant-oat-abcdef")
    with pytest.raises(ValueError, match="API key"):
        setup_token_from_paste("sk-ant-api03-nope")


def test_exchange_codex_code_posts_pkce() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://auth.openai.com/oauth/token"
        body = request.content.decode("ascii")
        assert "grant_type=authorization_code" in body
        assert "code=abc" in body
        assert "code_verifier=ver" in body
        return httpx.Response(
            200,
            json={"access_token": "atok", "refresh_token": "rtok", "expires_in": 60},
        )

    token = exchange_codex_code(
        "abc",
        verifier="ver",
        state="st",
        expected_state="st",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert token.access_token == "atok"


def test_exchange_anthropic_code_posts_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["grant_type"] == "authorization_code"
        assert payload["code"] == "abc"
        assert payload["state"] == "st"
        return httpx.Response(
            200,
            json={"access_token": "claude-tok", "refresh_token": "r", "expires_in": 60},
        )

    token = exchange_anthropic_code(
        "abc#st",
        verifier="ver",
        expected_state="st",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert token.access_token == "claude-tok"


def test_xai_device_code_and_pending_poll() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/device/code"):
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://auth.x.ai/activate",
                    "verification_uri_complete": "https://auth.x.ai/activate?user_code=ABCD-1234",
                    "expires_in": 120,
                    "interval": 1,
                },
            )
        return httpx.Response(400, json={"error": "authorization_pending"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    device = request_device_code(client=client)
    assert device.user_code == "ABCD-1234"
    with pytest.raises(AuthorizationPending):
        poll_device_token(device, client=client)


def test_oauth_counts_as_configured_without_api_key() -> None:
    assert configured_provider_ids() == ()
    save_token("openai", OAuthToken(access_token="tok", account_id="acct"))
    assert get_provider("openai").supports_oauth
    assert provider_is_configured(get_provider("openai"))
    assert configured_provider_ids() == ("openai",)


def test_build_default_registry_uses_codex_oauth() -> None:
    save_token("openai", OAuthToken(access_token="tok", account_id="acct"))
    registry = build_default_registry()
    provider = registry._providers["openai"]
    assert isinstance(provider, OpenAIProvider)
    assert provider.api_key == "tok"
    assert provider.base_url == CODEX_BASE_URL
    assert provider.extra_headers["ChatGPT-Account-Id"] == "acct"
    assert provider.extra_headers["originator"] == "symphony"


def test_build_default_registry_prefers_api_key_over_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    save_token("openai", OAuthToken(access_token="oauth-tok", account_id="acct"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    registry = build_default_registry()
    provider = registry._providers["openai"]
    assert provider.api_key == "sk-env"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.extra_headers == {}


def test_build_default_registry_uses_anthropic_oauth_bearer() -> None:
    save_token("anthropic", OAuthToken(access_token="oat"))
    registry = build_default_registry()
    provider = registry._providers["anthropic"]
    assert isinstance(provider, AnthropicProvider)
    assert provider.use_bearer
    headers = provider._headers
    assert headers["Authorization"] == "Bearer oat"
    assert "x-api-key" not in headers
    assert headers["anthropic-beta"] == "oauth-2025-04-20"


def test_start_login_openai_paste_exchanges_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "live", "refresh_token": "r", "expires_in": 60},
        )

    flow = start_login(
        "openai",
        open_browser=False,
        bind_loopback=False,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    token = flow.complete_from_paste("http://localhost:1455/auth/callback?code=abc&state=" + flow._state)
    assert token.access_token == "live"
    flow.close()


def test_start_login_anthropic_setup_token() -> None:
    flow = start_login("anthropic", open_browser=False, bind_loopback=False)
    token = flow.complete_from_paste("sk-ant-oat-from-cli")
    assert token.access_token == "sk-ant-oat-from-cli"
    flow.close()


def test_token_from_response_sets_expiry() -> None:
    token = token_from_response({"access_token": "a", "expires_in": 100})
    assert token.access_token == "a"
    assert token.expires_at > time.time()


def test_oauth_runtime_none_without_token() -> None:
    assert oauth_runtime_for("openai") is None
    assert oauth_runtime_for("gemini") is None
