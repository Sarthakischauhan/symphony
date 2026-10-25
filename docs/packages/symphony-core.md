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

Realtime models (`api="realtime"`, today `grok:grok-voice-3.0` and `grok:grok-voice-latest`) list their voices, audio formats and `reasoning_efforts` on `ModelInfo`. Open one with `ModelRegistry.open_voice(model_id, VoiceConfig(voice=...), session_id=...)`: the returned `VoiceSession` carries audio both ways, and while it is open a harness run for the same `session_id` streams its model turns through it (`core_ai.voice_model_call`), so tools, history and the final message stay with the harness. Close it with `ModelRegistry.close_voice`.

To add tools and a model-driven run loop, continue to [symphony-harness](./symphony-harness.md).
