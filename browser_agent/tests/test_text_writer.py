"""The text writer is Grok or nothing, and an empty reply is not a crash."""

from __future__ import annotations

import pytest

from browser_agent.text_writer import GrokTextWriter, _parse_text, build_text_writer


def test_parse_text_handles_empty_json_and_lines() -> None:
    assert _parse_text("") == ""
    assert _parse_text("   \n ") == ""
    assert _parse_text('{"text": " travel "}') == "travel"
    assert _parse_text('"alps"\nmore') == "alps"


def test_non_grok_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="grok:"):
        build_text_writer("openai:gpt-5")


def test_grok_needs_xai_key_and_uses_the_catalog_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert build_text_writer() is None
    monkeypatch.setenv("GROK_API_KEY", "legacy")
    assert build_text_writer() is None
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    writer = build_text_writer()
    assert isinstance(writer, GrokTextWriter)
    assert writer.model.startswith("grok:")
    explicit = build_text_writer("grok:grok-mini")
    assert isinstance(explicit, GrokTextWriter) and explicit.model == "grok:grok-mini"
