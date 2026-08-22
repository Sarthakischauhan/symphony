# core-ai

Small shared package for model providers and streaming response types. It is under active development, with a focus on providing a `ModelRegistry`, streaming providers, and shared types like `Message` and `StreamEvent`.

## What it provides

- `ModelRegistry` for routing `provider:model` requests
- `OpenAIProvider`, `AnthropicProvider`, and `GeminiProvider` for streaming model output
- `build_default_registry()` to register every provider that has credentials in the environment
- A generated model catalog (`core_ai.models`) plus `Message` and `StreamEvent` as shared data types

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

Set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and/or `GEMINI_API_KEY` / `GOOGLE_API_KEY`. The default model is the first registered provider unless `SYMPHONY_MODEL` (or a provider-specific `*_MODEL`) is set.

## Model catalog

The shipped catalog in `src/core_ai/models/generated.py` is produced by `scripts/generate_models.py`. Packaging `core-ai` runs that script through a Hatch build hook:

- live `/models` endpoints are used when the matching API key is present
- otherwise the existing generated snapshot (or a small fallback) is kept, so builds do not require network access

Refresh the snapshot manually with:

```sh
uv run python scripts/generate_models.py
```

## Development

Run tests from this package directory:

```sh
uv run pytest
```
