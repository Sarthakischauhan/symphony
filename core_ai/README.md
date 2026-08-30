# core-ai

Small shared package for model providers and streaming response types. It is under active development, with a focus on providing a `ModelRegistry`, streaming providers, and shared types like `Message` and `StreamEvent`.

## What it provides

- `ModelRegistry` for routing `provider:model` requests
- `OpenAIProvider`, `AnthropicProvider`, and `GeminiProvider` for streaming model output
- `build_default_registry()` to register every provider that has credentials in the environment
- A generated model catalog (`ModelCatalog`, `ModelInfo`, `list_models()`, and `get_model()`)
- `Message` and `StreamEvent` as the provider-neutral message and stream contract
- Canonical text/image `Message.content` parts, translated per provider (`image_url`, `input_image`, Anthropic `image.source`, Gemini `inlineData`)

## Example

`core-ai` is used by the coding agent stack:

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()

agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".workspace",
)

result = await agent.run("Create hello.txt with hi, then read it back.")
print(result.output_text)
```

Set one or more provider credentials. Every provider with a key is registered:

| Provider | Credential | Optional base URL | Model override |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `OPENAI_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `ANTHROPIC_MODEL` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `GEMINI_BASE_URL` | `GEMINI_MODEL` |

`SYMPHONY_MODEL` has priority over provider-specific model variables. Model ids
should use `provider:model`; an unqualified explicit id is assigned to OpenAI
when OpenAI is registered, otherwise to the first registered provider. With no
model override, `default_model_id()` chooses the default for the first available
provider in OpenAI, Anthropic, Gemini order. It raises if no credential is set.

The providers translate streamed text, reasoning, tool calls, usage, completion,
and rate-limit retry signals into the shared `StreamEvent` format. OpenAI selects
Responses or Chat Completions from the catalog (with an `o1` / `o3` / `o4`
fallback); Anthropic uses Messages and Gemini uses streamGenerateContent.

## Model catalog

The shipped catalog in `src/core_ai/models/generated.py` is produced by
`scripts/generate_models.py`. It records each model's short id, provider, and API
family. Packaging `core-ai` runs the generator through a Hatch build hook:

- the curated `https://models.dev/models.json` catalog is used as the source of model ids
- only text-output models with tool-calling support are emitted for OpenAI, Anthropic, and Gemini
- the existing generated snapshot (or a small fallback) is kept when the catalog is unavailable, so builds remain resilient

The catalog is downloaded once per generation and filtered locally; the full upstream
response is never copied into the generated registry. Set `CORE_AI_MODELS_DEV=0`
to disable the refresh, or `MODELS_DEV_URL` to use a mirror/test endpoint.

Provider credentials are not needed to generate the catalog. They are still required
when constructing a provider and using a model.

Refresh the snapshot manually with:

```sh
uv run python scripts/generate_models.py
```

Set `CORE_AI_GENERATE_STRICT=1` to fail a manual refresh when a configured
provider request fails or returns no models. Without strict mode, the generator
keeps that provider's existing snapshot. `scripts/generate_openai_models.py`
remains as a backward-compatible wrapper around the combined generator.

Catalog entries can also be inspected or extended at runtime:

```python
from core_ai import ModelInfo, get_model, list_models
from core_ai.models import register_model

openai_models = list_models("openai")
model = get_model("openai", "gpt-4.1")
register_model(ModelInfo(id="local-model", provider="local", api="responses"))
```

## Development

Run tests from this package directory:

```sh
uv run pytest
```
