# symphony-core

Small shared package for model providers and streaming response types. It
ships a `ModelRegistry`, streaming providers, and shared types like `Message`
and `StreamEvent`.

> Import it as `core_ai`. APIs are evolving (0.1.0).

```sh
uv add symphony-core
```

Docs: **[symphony-core](../docs/packages/symphony-core.md)** ·
[Installation](../docs/getting-started/installation.md) ·
[Environment](../docs/reference/environment.md)

## What it provides

- `ModelRegistry` for routing `provider:model` requests
- `OpenAIProvider`, `AnthropicProvider`, `GeminiProvider`, `GrokProvider`,
  `OllamaProvider`, and `LocalProvider` for streaming model output
- `build_default_registry()` to register every provider that has credentials
  in the environment
- A generated model catalog (`ModelCatalog`, `ModelInfo`, `list_models()`,
  and `get_model()`)
- `Message` and `StreamEvent` as the provider-neutral message and stream
  contract
- Canonical text/image `Message.content` parts, translated per provider
  (`image_url`, `input_image`, Anthropic `image.source`, Gemini `inlineData`)

## Example

```python
from core_ai import build_default_registry, default_model_id, list_models

registry = build_default_registry()
model_id = default_model_id(registry)
openai_models = list_models("openai")
print(model_id, len(openai_models))
```

Set one or more provider credentials. Cloud providers register from an API
key. Ollama and local servers are opt-in (no localhost probe):

| Provider | Credential | Optional base URL | Model override |
| --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `OPENAI_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `ANTHROPIC_MODEL` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `GEMINI_BASE_URL` | `GEMINI_MODEL` |
| Grok | `XAI_API_KEY` | `XAI_BASE_URL` | `GROK_MODEL` or `XAI_MODEL` |
| Ollama | `OLLAMA_ENABLED=1`, `OLLAMA_BASE_URL`, or `OLLAMA_HOST` | `OLLAMA_BASE_URL` | `OLLAMA_MODEL` |
| Local | `LOCAL_BASE_URL` | — | `LOCAL_MODEL` |

`SYMPHONY_MODEL` has priority over provider-specific model variables. Model
ids should use `provider:model`; an unqualified explicit id is assigned to
OpenAI when OpenAI is registered, otherwise to the first registered provider.
With no model override, `default_model_id()` chooses the default for the first
available provider in OpenAI, Anthropic, Gemini, Grok, Ollama, Local order.
For Ollama/local it prefers a discovered model (or `OLLAMA_MODEL` /
`LOCAL_MODEL`). It raises if no credential or local opt-in is set.

The providers translate streamed text, reasoning, tool calls, usage,
completion, and retry signals (429, SSL MAC, 5xx, connection) into the shared
`StreamEvent` format. OpenAI selects Responses or Chat Completions from the
catalog (with an `o1` / `o3` / `o4` fallback); Anthropic uses Messages,
Gemini uses streamGenerateContent, and Grok, Ollama, and local servers use
Chat Completions. Ollama/local omit `stream_options` and send `max_tokens`,
matching OpenAI-compatible daemons.

## Model catalog

The shipped catalog in `src/core_ai/models/generated.py` is a **checked-in
snapshot**. It records each model's short id, provider, API family, and
reasoning options. Installing or building `symphony-core` ships that file
as-is: the build never contacts the network and never rewrites the snapshot.

The snapshot is produced by the maintainer script `scripts/generate_models.py`:

- the curated [models.dev](https://models.dev) catalog
  (`https://models.dev/api.json`) is the source of model ids
- only text-output models with tool-calling support are emitted for OpenAI,
  Anthropic, Gemini, and Grok (plus OpenAI `gpt-image-*` models)
- the catalog is downloaded once per run and filtered locally; the full
  upstream response is never copied into the generated registry

Refresh the snapshot and commit the result:

```sh
cd core_ai
uv run python scripts/generate_models.py
```

| Variable | Effect on `scripts/generate_models.py` |
| --- | --- |
| `CORE_AI_GENERATE_STRICT=1` | Fail instead of keeping the existing snapshot when models.dev is unreachable or returns nothing |
| `CORE_AI_MODELS_DEV=0` | Skip the network entirely; rewrite the file from the existing snapshot (or the small built-in fallback) |
| `MODELS_DEV_URL` | Mirror or test endpoint instead of `https://models.dev/api.json` |

For a one-off refresh during packaging, set `CORE_AI_REFRESH_CATALOG=1` when
building. The Hatch hook (`hatch_build.py`) then regenerates the catalog in
strict mode and fails the build if models.dev cannot be reached. It needs
`httpx` in the build environment (for example `uv build --no-build-isolation`
inside the workspace). Without that variable the hook does nothing.

Provider credentials are not needed to generate the catalog. They are still
required when constructing a provider and using a model.

Catalog entries can also be inspected or extended at runtime:

```python
from core_ai import ModelInfo, get_model, list_models
from core_ai.models import register_model

openai_models = list_models("openai")
model = get_model("openai", "gpt-4.1")
register_model(ModelInfo(id="local-model", provider="custom", api="chat_completions"))
```

## Development

Run tests from this package directory:

```sh
uv run pytest
```
