from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

CORE_AI = Path(__file__).resolve().parents[1]
SCRIPT = CORE_AI / "scripts" / "generate_models.py"


def load_generate_models():
    spec = importlib.util.spec_from_file_location("generate_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_without_existing_file_uses_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generate_models = load_generate_models()
    output = tmp_path / "generated.py"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("CORE_AI_MODELS_DEV", "0")

    generate_models.generate(output=output)

    catalog = generate_models.read_existing_catalog(output)
    assert catalog["openai"] == list(generate_models.FALLBACK_MODELS["openai"])
    assert catalog["anthropic"] == list(generate_models.FALLBACK_MODELS["anthropic"])
    assert catalog["gemini"] == list(generate_models.FALLBACK_MODELS["gemini"])
    assert catalog["grok"] == list(generate_models.FALLBACK_MODELS["grok"])
    assert "ALL_MODELS = OPENAI_MODELS + ANTHROPIC_MODELS + GEMINI_MODELS + GROK_MODELS" in output.read_text()


def test_generate_without_keys_keeps_existing_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generate_models = load_generate_models()
    output = tmp_path / "generated.py"
    output.write_text(
        generate_models.render(
            {
                "openai": [("gpt-custom", "responses")],
                "anthropic": [("claude-custom", "messages")],
                "gemini": [("gemini-custom", "generate_content")],
                "grok": [("grok-custom", "chat_completions")],
            }
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("CORE_AI_MODELS_DEV", "0")

    generate_models.generate(output=output)

    catalog = generate_models.read_existing_catalog(output)
    assert catalog["openai"] == [("gpt-custom", "responses")]
    assert catalog["anthropic"] == [("claude-custom", "messages")]
    assert catalog["gemini"] == [("gemini-custom", "generate_content")]
    assert catalog["grok"] == [("grok-custom", "chat_completions")]


def test_generate_uses_curated_models_dev_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generate_models = load_generate_models()
    output = tmp_path / "generated.py"
    def fake_get(url: str, *args, **kwargs):
        assert url == generate_models.MODELS_DEV_URL
        return type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {
                "openai": {
                    "id": "openai",
                    "models": {
                        "gpt-4.1-mini": {
                            "tool_call": True, "modalities": {"output": ["text"]}
                        },
                        "o3": {
                            "tool_call": True, "modalities": {"output": ["text"]}
                        },
                        "whisper-1": {
                            "tool_call": False, "modalities": {"output": ["audio"]}
                        },
                    },
                },
                "anthropic": {
                    "id": "anthropic",
                    "models": {
                        "claude-sonnet-5": {
                            "tool_call": True, "modalities": {"output": ["text"]}
                        },
                    },
                },
                "google": {
                    "id": "google",
                    "models": {
                        "gemini-3.7-flash": {
                            "tool_call": True, "modalities": {"output": ["text"]}
                        },
                        "gemini-3.7-flash-image": {
                            "tool_call": True, "modalities": {"output": ["image"]}
                        },
                    },
                },
                "xai": {
                    "id": "xai",
                    "models": {
                        "grok-4.6": {
                            "tool_call": True,
                            "reasoning": True,
                            "modalities": {"output": ["text"]},
                            "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high", "xhigh"]}],
                        },
                        "grok-imagine-image": {
                            "tool_call": False, "modalities": {"output": ["image"]}
                        },
                    },
                },
            },
        })()

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setenv("MODELS_DEV_URL", generate_models.MODELS_DEV_URL)
    generate_models.generate(output=output)
    text = output.read_text()
    assert 'ModelInfo(id="gpt-4.1-mini", provider="openai", api="responses")' in text
    assert 'ModelInfo(id="o3", provider="openai", api="chat_completions")' in text
    assert "whisper-1" not in text
    assert 'ModelInfo(id="claude-sonnet-5", provider="anthropic", api="messages")' in text
    assert 'ModelInfo(id="gemini-3.7-flash", provider="gemini", api="generate_content")' in text
    assert "gemini-3.7-flash-image" not in text
    assert 'ModelInfo(id="grok-4.6", provider="grok", api="chat_completions", reasoning=True' in text
    assert "grok-imagine-image" not in text


def load_hatch_build():
    spec = importlib.util.spec_from_file_location("hatch_build", CORE_AI / "hatch_build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hook(hatch_build, root: Path):
    """Build a hook without hatchling's constructor; only ``root`` and ``app`` are used."""

    class TestHook(hatch_build.CustomBuildHook):
        @property
        def root(self) -> str:
            return str(root)

        @property
        def app(self):
            return SimpleNamespace(display_info=lambda *_: None)

    return TestHook.__new__(TestHook)


def test_hatch_build_hook_is_wired_in_pyproject() -> None:
    pyproject = (CORE_AI / "pyproject.toml").read_text()
    assert 'path = "hatch_build.py"' in pyproject
    assert 'build-backend = "hatchling.build"' in pyproject
    # Default builds must not need network clients in the build environment.
    assert "httpx" not in pyproject.split("[build-system]")[1].split("[tool.hatch")[0]


def test_hatch_build_hook_ships_snapshot_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hatch_build = load_hatch_build()
    monkeypatch.delenv(hatch_build.REFRESH_ENV, raising=False)
    calls: list[Path] = []
    monkeypatch.setattr(hatch_build, "refresh_catalog", lambda root: calls.append(root))

    _hook(hatch_build, tmp_path).initialize("standard", {})

    assert calls == []
    assert not hatch_build.refresh_requested({})
    assert not hatch_build.refresh_requested({hatch_build.REFRESH_ENV: "0"})


def test_hatch_build_hook_refreshes_only_when_asked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hatch_build = load_hatch_build()
    monkeypatch.setenv(hatch_build.REFRESH_ENV, "1")
    calls: list[Path] = []
    monkeypatch.setattr(hatch_build, "refresh_catalog", lambda root: calls.append(root))

    _hook(hatch_build, tmp_path).initialize("standard", {})

    assert calls == [tmp_path]
    assert hatch_build.refresh_requested({hatch_build.REFRESH_ENV: "true"})


def test_hatch_build_refresh_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    hatch_build = load_hatch_build()

    def failing_get(url: str, *args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", failing_get)
    monkeypatch.delenv("CORE_AI_MODELS_DEV", raising=False)
    snapshot = CORE_AI / "src" / "core_ai" / "models" / "generated.py"
    before = snapshot.read_text()
    with pytest.raises(httpx.ConnectError):
        hatch_build.refresh_catalog(CORE_AI)
    assert snapshot.read_text() == before
