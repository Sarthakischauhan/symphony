from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Input, OptionList, Static

from coding_agent.credentials import global_env_path, workspace_env_path
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.screens.onboard import OnboardApp, ProviderOnboardScreen
from core_ai.oauth import LoginCancelled
from core_ai.oauth.types import LoginPrompt, OAuthToken
from core_ai.providers.catalog import PROVIDERS, configured_provider_ids


PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "SYMPHONY_OPENAI_AUTH",
    "SYMPHONY_ANTHROPIC_AUTH",
    "SYMPHONY_GROK_AUTH",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "AI_GATEWAY_API_KEY",
    "VERCEL_AI_GATEWAY_API_KEY",
    "SYMPHONY_MODEL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_ENABLED",
    "OLLAMA_MODEL",
    "LOCAL_API_KEY",
    "LOCAL_BASE_URL",
    "LOCAL_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _highlight_provider(app: OnboardApp, provider_id: str) -> None:
    listing = app.query_one("#provider-list", OptionList)
    listing.highlighted = next(
        index for index, spec in enumerate(PROVIDERS) if spec.id == provider_id
    )


async def _choose_api_key(pilot: Any, app: Any) -> None:
    listing = app.query_one("#provider-list", OptionList)
    listing.highlighted = 1
    await pilot.press("enter")
    await pilot.pause()


class _FakeFlow:
    def __init__(self, provider_id: str) -> None:
        self.prompt = LoginPrompt(
            provider_id=provider_id,
            kind="paste",
            title="Sign in with ChatGPT",
            instructions="Paste the redirect URL.",
            url="https://auth.openai.com/oauth/authorize?fake=1",
            paste_hint="http://localhost:1455/auth/callback?code=...",
        )
        self.closed = False
        self._event = threading.Event()
        self._token = OAuthToken(access_token="codex-access", account_id="acct_1", refresh_token="r")

    def wait(self, timeout: float = 300.0) -> OAuthToken:
        self._event.wait(timeout)
        if self.closed:
            raise LoginCancelled()
        return self._token

    def complete_from_paste(self, pasted: str) -> OAuthToken:
        del pasted
        self._event.set()
        return self._token

    def close(self) -> None:
        self.closed = True
        self._event.set()


def test_onboard_saves_key_and_continues(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await _choose_api_key(pilot, app)
            key = app.query_one("#provider-key", Input)
            assert key.password
            key.value = "sk-test-openai"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ("openai",)
    env_path = global_env_path()
    assert env_path == (Path.home() / ".symphony" / ".env").resolve()
    assert "OPENAI_API_KEY=sk-test-openai" in env_path.read_text(encoding="utf-8")
    assert not workspace_env_path(tmp_path).exists()
    assert configured_provider_ids() == ("openai",)


def test_onboard_reuses_existing_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-existing")
    monkeypatch.setenv("SYMPHONY_OPENAI_AUTH", "oauth")
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            methods = app.query_one("#provider-list", OptionList)
            assert "Use existing API key" in str(methods.get_option_at_index(1).prompt)
            await _choose_api_key(pilot, app)
            assert not app.query_one("#provider-key", Input).display
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ("openai",)
    assert os.environ["OPENAI_API_KEY"] == "sk-existing"
    assert os.environ["SYMPHONY_OPENAI_AUTH"] == "key"
    assert "SYMPHONY_OPENAI_AUTH=key" in global_env_path().read_text(
        encoding="utf-8"
    )


def test_onboard_adds_two_providers(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await _choose_api_key(pilot, app)
            app.query_one("#provider-key", Input).value = "sk-openai"
            await pilot.press("enter")
            await pilot.pause()
            listing = app.query_one("#provider-list", OptionList)
            listing.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()
            await _choose_api_key(pilot, app)
            app.query_one("#provider-key", Input).value = "sk-ant-test"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ("openai", "anthropic")
    text = global_env_path().read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-openai" in text
    assert "ANTHROPIC_API_KEY=sk-ant-test" in text
    assert not workspace_env_path(tmp_path).exists()


def test_onboard_oauth_saves_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeFlow("openai")
    monkeypatch.setenv("SYMPHONY_OPENAI_AUTH", "key")
    monkeypatch.setattr("coding_agent.tui.screens.onboard.start_login", lambda provider_id, **kwargs: fake)
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            key = app.query_one("#provider-key", Input)
            assert not key.password
            key.value = "http://localhost:1455/auth/callback?code=abc"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ("openai",)
    token_file = Path.home() / ".symphony" / "oauth" / "openai.json"
    assert token_file.is_file()
    assert "codex-access" in token_file.read_text(encoding="utf-8")
    assert "SYMPHONY_OPENAI_AUTH=oauth" in global_env_path().read_text(
        encoding="utf-8"
    )
    assert configured_provider_ids() == ("openai",)


def test_onboard_ollama_blank_submit_writes_default_base_url(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            _highlight_provider(app, "ollama")
            await pilot.press("enter")
            await pilot.pause()
            key = app.query_one("#provider-key", Input)
            assert not key.password
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ("ollama",)
    text = global_env_path().read_text(encoding="utf-8")
    assert "OLLAMA_BASE_URL=http://localhost:11434/v1" in text
    assert configured_provider_ids() == ("ollama",)


def test_onboard_local_requires_base_url(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            _highlight_provider(app, "local")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            error = str(app.query_one("#onboard-error", Static).render())
            assert "base URL" in error
            assert app.query_one("#provider-key", Input).display
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ()
    assert not global_env_path().exists()


def test_onboard_escape_skips_without_writing(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(_run())

    assert app.return_value == ()
    assert not global_env_path().exists()
    assert not workspace_env_path(tmp_path).exists()


def test_onboard_escape_on_key_step_returns_to_picker(tmp_path: Path) -> None:
    app = OnboardApp(tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await _choose_api_key(pilot, app)
            assert app.query_one("#provider-key", Input).display
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#provider-list", OptionList).display
            assert not app.query_one("#provider-key", Input).display
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#provider-list", OptionList).display

    asyncio.run(_run())
    assert app.return_value is None
    assert not global_env_path().exists()
    assert not workspace_env_path(tmp_path).exists()


def test_provider_command_opens_onboard_while_offline(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._agent is None
            await app._command_manager.run("/provider")
            await pilot.pause()
            assert isinstance(app.screen, ProviderOnboardScreen)

    asyncio.run(_run())


def test_provider_command_escape_closes_onboard(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._command_manager.run("/provider")
            await pilot.pause()
            assert isinstance(app.screen, ProviderOnboardScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert not isinstance(app.screen, ProviderOnboardScreen)

    asyncio.run(_run())


def test_provider_command_unknown_name_stays_on_chat(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._command_manager.run("/provider nope")
            await pilot.pause()
            assert app.screen is app.screen
            assert not isinstance(app.screen, ProviderOnboardScreen)

    asyncio.run(_run())


def test_provider_onboard_reloads_agent_after_existing_provider_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    loaded: list[Path] = []
    reloaded_agent = SimpleNamespace(
        session_id="new-session",
        harness=SimpleNamespace(
            model_id="openai:gpt-5.6-luna",
            reasoning_effort=None,
            state=SimpleNamespace(context_limit=lambda _model_id: 64_000),
        ),
        registry=SimpleNamespace(namespaces=lambda: ("openai",)),
        learning_loop=None,
        set_mode=lambda _mode: None,
    )

    def _load_provider_env(workspace: Path) -> None:
        loaded.append(Path(workspace))

    def _build_agent(**kwargs: Any) -> Any:
        del kwargs
        return reloaded_agent

    monkeypatch.setattr("coding_agent.tui.commands.manager.load_provider_env", _load_provider_env)
    monkeypatch.setattr("coding_agent.tui.commands.manager.build_agent", _build_agent)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent = SimpleNamespace(
                session_id="current-session",
                harness=SimpleNamespace(reasoning_effort=None),
                registry=SimpleNamespace(namespaces=lambda: ("openai",)),
                learning_loop=None,
            )
            await app._command_manager.run("/provider openai")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ProviderOnboardScreen)
            await _choose_api_key(pilot, screen)
            screen.query_one("#provider-key", Input).value = "sk-live"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

    asyncio.run(_run())
    assert loaded == [tmp_path]
    assert app._agent is reloaded_agent
