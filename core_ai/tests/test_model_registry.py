from core_ai.models import ModelCatalog, ModelInfo, get_model, register_model, unregister_model
from core_ai.providers.openai import OpenAIProvider


def test_catalog_supports_dynamic_model_registration() -> None:
    catalog = ModelCatalog()
    model = ModelInfo(id="future-model", provider="openai", api="responses")

    catalog.register(model)

    assert catalog.get("openai", "future-model") == model
    assert catalog.list("openai") == (model,)

    catalog.unregister("openai", "future-model")
    assert catalog.get("openai", "future-model") is None


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
