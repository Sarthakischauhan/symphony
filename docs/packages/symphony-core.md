# symphony-core

Provider integrations and shared model-stream types for Symphony agents. The package imports as `core_ai`. It does not run an agent by itself.

**Availability:** published on PyPI as version 0.0.1. Install with `pip install symphony-core`, or use a checkout as described in [Install Symphony](../getting-started/installation.md). Import name: `core_ai`.

## Use a configured provider

```python
from core_ai import build_default_registry, default_model_id

registry = build_default_registry()
model_id = default_model_id(registry)
print(model_id)  # provider:model
```

A provider is registered when its credentials are available; local providers are opt-in. Set model credentials and defaults as described in the [environment reference](../reference/environment.md).

## Public building blocks

- `ModelRegistry` selects a provider from `provider:model` identifiers.
- Provider adapters stream through the shared `Message` and `StreamEvent` contracts.
- `build_default_registry()` discovers supported configured providers.
- `ModelCatalog`, `ModelInfo`, `list_models()`, and `get_model()` expose the checked-in model catalog.

The catalog is a checked-in snapshot. Normal builds do not refresh it or require a network connection. Maintainer refresh instructions live with [`core_ai`](../../core_ai/README.md).

## Realtime voice models

Voice models live in `core_ai.voice`, apart from the text catalog: `ALL_MODELS`, `list_models()` and `model_catalog` hold no `api="realtime"` model. `core_ai.voice.voice_catalog` lists them (today `grok:grok-voice-3.0` and `grok:grok-voice-latest`) with their voices, audio formats and `reasoning_efforts`. Build a `VoiceRegistry(context_limits)` with a token limit for every catalog model (xAI publishes no context window for its realtime models, so it is required config and a missing one raises `MissingVoiceContextLimit`), optionally on your own `ModelCatalog`, register a provider (`registry.register("grok", GrokRealtime(api_key))`), and `await registry.open(model_id, VoiceConfig(voice=...))` returns a `VoiceSession`: PCM audio both ways, typed events, and `response()` for each response the caller requested (`respond()`, matched by the `request_id` xAI echoes in response metadata, or the server-VAD answer to the utterance that just ended, until the next `speech_started`). Responses nobody requested are dropped. `add_tool_call`/`add_tool_result` seed tool turns for history replay. The package holds no tools, history or turn logic; per-provider modules sit under `core_ai.voice.<provider>` (`grok/realtime.py`, `events.py`, `payload.py`, `responses.py`; TTS and STT clients go beside it).

To add tools and a model-driven run loop, continue to [symphony-harness](./symphony-harness.md).
