import pytest

from core_ai.models.discovery import parse_models


def test_discovery_projects_only_supported_text_tool_models():
    payload = {"openai": {"models": {
        "gpt-6.2-astra": {"tool_call": True, "reasoning": True, "modalities": {"output": ["text"]},
                          "limit": {"context": 1050000}, "cost": {"input": 8, "output": 40},
                          "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high"]}]},
        "audio-only": {"tool_call": True, "modalities": {"output": ["audio"]}},
        "retired": {"tool_call": True, "modalities": {"output": ["text"]}, "status": "retired"},
        "../bad": {"tool_call": True, "modalities": {"output": ["text"]}},
    }}}
    (model,) = parse_models(payload, {"openai"})
    assert model.full_id == "openai:gpt-6.2-astra"
    assert model.api == "responses" and model.context_limit == 1050000
    assert model.reasoning and dict(model.thinking_level_map)["off"] is None
    assert model.price.input == 8
    assert parse_models(payload, {"gemini"}) == ()


def test_invalid_payload_rejected():
    with pytest.raises(ValueError):
        parse_models([], {"openai"})
