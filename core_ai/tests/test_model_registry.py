from core_ai.models import ModelCatalog, ModelInfo, get_model, list_models, register_model, unregister_model
from core_ai.providers.openai import OpenAIProvider


def test_catalog_supports_dynamic_model_registration() -> None:
    catalog = ModelCatalog()
    model = ModelInfo(id="future-model", provider="openai", api="responses")

    catalog.register(model)

    assert catalog.get("openai", "future-model") == model
    assert catalog.list("openai") == (model,)

    catalog.unregister("openai", "future-model")
    assert catalog.get("openai", "future-model") is None


def test_shipped_catalog_includes_openai_anthropic_gemini_and_grok() -> None:
    openai = list_models("openai")
    anthropic = list_models("anthropic")
    gemini = list_models("gemini")
    grok = list_models("grok")

    assert any(model.id == "gpt-5.6-luna" and model.api == "responses" for model in openai)
    assert any(model.id == "gpt-image-2" and model.api == "responses" for model in openai)
    assert any(model.id == "claude-sonnet-5" and model.api == "messages" for model in anthropic)
    assert any(model.id == "gemini-3.7-flash" and model.api == "generate_content" for model in gemini)
    assert any(model.id == "grok-4.6" and model.api == "chat_completions" for model in grok)
    assert get_model("anthropic", "claude-opus-5") is not None
    assert get_model("gemini", "gemini-3.1-pro-preview") is not None
    assert get_model("grok", "grok-4.6") is not None


def test_openai_provider_uses_registered_model_api() -> None:
    model = ModelInfo(
        id="future-reasoning-model",
        provider="openai",
        api="chat_completions",
    )
    register_model(model)
    try:
        assert get_model("openai", model.id) == model
        assert OpenAIProvider._uses_chat_completions(model.id) is True
    finally:
        unregister_model("openai", model.id)


def test_openai_provider_keeps_unknown_model_fallback() -> None:
    assert OpenAIProvider._uses_chat_completions("o4-future") is True
    assert OpenAIProvider._uses_chat_completions("gpt-future") is False
