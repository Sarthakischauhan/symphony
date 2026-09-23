from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

for src_path in (
    ROOT / "src",
    REPO_ROOT / "core_harness" / "src",
    REPO_ROOT / "core_ai" / "src",
):
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent developer credentials from enabling providers during tests."""
    for name in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "XAI_API_KEY", "OPENROUTER_API_KEY", "VERCEL_AI_GATEWAY_API_KEY",
        "AI_GATEWAY_API_KEY", "SYMPHONY_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL",
        "GEMINI_MODEL", "GROK_MODEL", "XAI_MODEL", "OPENROUTER_MODEL",
        "VERCEL_MODEL", "AI_GATEWAY_MODEL", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
        "GEMINI_BASE_URL", "XAI_BASE_URL", "OPENROUTER_BASE_URL",
        "AI_GATEWAY_BASE_URL", "OLLAMA_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_HOST",
        "OLLAMA_ENABLED", "OLLAMA_MODEL", "LOCAL_API_KEY", "LOCAL_BASE_URL",
        "LOCAL_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolate_symphony_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    return home
