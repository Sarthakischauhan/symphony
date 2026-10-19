"""Hermetic environment shared by every package's tests.

Each test gets an empty HOME and SYMPHONY_HOME under its own tmp dir, and no
provider, model, auth, or tracing variable from the developer's shell (``uv
run`` can also load ``~/.env``), nor a ``GIT_*`` variable exported by a git
hook. Nothing reads the real ``~/.symphony`` config, OAuth tokens, or keys, so
a local setup cannot change which provider or model a test sees. Worker
subprocesses inherit this env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core_ai.providers.catalog import PROVIDERS

_ENV_NAMES = (
    "SYMPHONY_HOME",
    "SYMPHONY_MODEL",
    "SYMPHONY_JEV_PROVIDER",
    "SYMPHONY_BROWSER_TEXT_MODEL",
    "JEV_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
    "OPENROUTER_MODEL",
    "OPENROUTER_DECISIONS_URL",
    "VERCEL_MODEL",
    "AI_GATEWAY_MODEL",
    "OLLAMA_MODEL",
    "LOCAL_MODEL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


def _provider_env_names() -> set[str]:
    names = set(_ENV_NAMES)
    for spec in PROVIDERS:
        names.update(name for name in (spec.env_key, *spec.env_aliases) if name)
        names.update(name for name in (spec.base_url_env, spec.host_env, spec.enabled_env) if name)
        names.add(f"SYMPHONY_{spec.id.upper()}_AUTH")
    return names


PROVIDER_ENV = frozenset(_provider_env_names())


def _playwright_browsers() -> str:
    """Playwright's browser cache under the real home, resolved before HOME is swapped."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if configured:
        return configured
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Caches" / "ms-playwright")
    if sys.platform == "win32":
        return str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright")


PLAYWRIGHT_BROWSERS = _playwright_browsers()


@pytest.fixture(autouse=True)
def hermetic_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME and SYMPHONY_HOME at a fresh tmp dir and drop provider env."""
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    # A git hook exports GIT_DIR/GIT_INDEX_FILE. Left in place, a test that runs
    # `git init && git commit` in its tmp dir writes into the outer repository.
    for name in [key for key in os.environ if key.startswith("GIT_") and key != "GIT_EXEC_PATH"]:
        monkeypatch.delenv(name)
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SYMPHONY_HOME", str(home / ".symphony"))
    # Browsers are a download cache, not user config: keep finding them.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", PLAYWRIGHT_BROWSERS)
    return home
