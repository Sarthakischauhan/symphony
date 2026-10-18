# symphony-core

Provider integrations and model-neutral streaming types for Symphony agents. Python import: `core_ai`.

**Availability:** version 0.0.1 is on PyPI: `pip install symphony-core`. Import name: `core_ai`. Development still uses the repository workspace; see the [installation guide](../docs/getting-started/installation.md).

## Minimal example

```python
from core_ai import build_default_registry, default_model_id

registry = build_default_registry()
model_id = default_model_id(registry)
print(model_id)  # provider:model
```

The registry includes supported cloud providers for which credentials are configured. Ollama and generic local OpenAI-compatible providers are opt-in. See the [provider/environment reference](../docs/reference/environment.md).

## What the package provides

- Provider adapters for OpenAI, Anthropic, Gemini, Grok, OpenRouter, Vercel AI Gateway, Ollama, and compatible local endpoints.
- `ModelRegistry` and provider-prefixed model IDs (`provider:model`).
- Provider-independent `Message` and `StreamEvent` types, including streamed text and tool calls.
- A checked-in generated catalog of supported tool-calling models; ordinary installation/build does not refresh it.

For public interfaces and streaming behavior, see the [symphony-core guide](../docs/packages/symphony-core.md). To build an agent that uses these providers, continue to [symphony-harness](../docs/packages/symphony-harness.md).

## Maintainer: refresh the checked-in catalog

The generated model list is a snapshot; building the workspace never updates it. To deliberately refresh and commit the catalog:

```sh
cd core_ai
uv run python scripts/generate_models.py
```

The script reads models.dev. When that source is unavailable, it keeps the existing snapshot unless `CORE_AI_GENERATE_STRICT=1` is set. See [`scripts/generate_models.py`](scripts/generate_models.py) for maintainer options.
