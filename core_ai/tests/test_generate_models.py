from __future__ import annotations

import importlib.util
from pathlib import Path

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

    generate_models.generate(output=output)

    catalog = generate_models.read_existing_catalog(output)
    assert catalog["openai"] == list(generate_models.FALLBACK_MODELS["openai"])
    assert catalog["anthropic"] == list(generate_models.FALLBACK_MODELS["anthropic"])
    assert catalog["gemini"] == list(generate_models.FALLBACK_MODELS["gemini"])
    assert "ALL_MODELS = OPENAI_MODELS + ANTHROPIC_MODELS + GEMINI_MODELS" in output.read_text()


def test_generate_without_keys_keeps_existing_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generate_models = load_generate_models()
    output = tmp_path / "generated.py"
    output.write_text(
        generate_models.render(
            {
                "openai": [("gpt-custom", "responses")],
                "anthropic": [("claude-custom", "messages")],
                "gemini": [("gemini-custom", "generate_content")],
            }
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    generate_models.generate(output=output)

    catalog = generate_models.read_existing_catalog(output)
    assert catalog["openai"] == [("gpt-custom", "responses")]
    assert catalog["anthropic"] == [("claude-custom", "messages")]
    assert catalog["gemini"] == [("gemini-custom", "generate_content")]


def test_generate_fetches_live_provider_catalogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generate_models = load_generate_models()
    output = tmp_path / "generated.py"
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_get(url: str, *args, **kwargs):
        if "api.openai.com" in url:
            return FakeResponse({"data": [{"id": "gpt-4.1-mini"}, {"id": "o3"}, {"id": "whisper-1"}]})
        if "api.anthropic.com" in url:
            params = kwargs.get("params") or {}
            if params.get("after_id") == "claude-sonnet-5":
                return FakeResponse(
                    {"data": [{"id": "claude-opus-5"}], "has_more": False, "last_id": "claude-opus-5"}
                )
            return FakeResponse(
                {"data": [{"id": "claude-sonnet-5"}], "has_more": True, "last_id": "claude-sonnet-5"}
            )
        if "generativelanguage.googleapis.com" in url:
            params = kwargs.get("params") or {}
            if params.get("pageToken") == "next":
                return FakeResponse(
                    {
                        "models": [
                            {
                                "name": "models/gemini-3.7-flash",
                                "supportedGenerationMethods": ["generateContent"],
                            },
                            {
                                "name": "models/gemini-3.7-flash-image",
                                "supportedGenerationMethods": ["generateContent"],
                            },
                        ]
                    }
                )
            return FakeResponse(
                {
                    "models": [
                        {
                            "name": "models/gemini-2.0-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "next",
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "get", fake_get)
    generate_models.generate(output=output)
    text = output.read_text()
    assert 'ModelInfo(id="gpt-4.1-mini", provider="openai", api="responses")' in text
    assert 'ModelInfo(id="o3", provider="openai", api="chat_completions")' in text
    assert "whisper-1" not in text
    assert 'ModelInfo(id="claude-sonnet-5", provider="anthropic", api="messages")' in text
    assert 'ModelInfo(id="claude-opus-5", provider="anthropic", api="messages")' in text
    assert 'ModelInfo(id="gemini-3.7-flash", provider="gemini", api="generate_content")' in text
    assert "gemini-2.0-flash" not in text
    assert "gemini-3.7-flash-image" not in text


def test_hatch_build_hook_regenerates_catalog_on_package() -> None:
    source = (CORE_AI / "hatch_build.py").read_text()
    pyproject = (CORE_AI / "pyproject.toml").read_text()
    assert "class CustomBuildHook" in source
    assert "from generate_models import generate" in source
    assert "generate(strict=False)" in source
    assert 'path = "hatch_build.py"' in pyproject
    assert 'build-backend = "hatchling.build"' in pyproject
