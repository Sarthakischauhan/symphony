# symphony-core

`symphony-core` is the smallest package. It does not run an agent. It routes
`provider:model` ids, streams OpenAI / Anthropic / Gemini / Grok through one event
contract, and ships a generated catalog of tool-calling text models.

```sh
uv add symphony-core
```

Import it as `core_ai`. The public API is re-exported from that module.

See also the [PyPI-facing README](../../core_ai/README.md).

## What it provides

- `ModelRegistry` routes `provider:model` requests.
- `OpenAIProvider`, `AnthropicProvider`, `GeminiProvider`, `GrokProvider` stream model output.
- `build_default_registry()` registers every provider that has credentials in
  the environment.
- Generated catalog: `ModelCatalog`, `ModelInfo`, `list_models()`, `get_model()`.
- `Message` and `StreamEvent` are the provider-neutral contracts.
- Canonical text/image `Message.content` parts, translated per provider
  (`image_url`, `input_image`, Anthropic `image.source`, Gemini `inlineData`).

## Minimal usage

```python
from core_ai import build_default_registry, default_model_id, list_models

registry = build_default_registry()
model_id = default_model_id(registry)   # first available: OpenAI, Anthropic, Gemini, Grok
openai_models = list_models("openai")
print(model_id, len(openai_models))
```

## How models are chosen

1. An explicit id (`--model`, constructor `model_id`, or a run request).
2. `SYMPHONY_MODEL`.
3. Provider-specific `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `GEMINI_MODEL` / `GROK_MODEL`.
4. `default_model_id()` — default for the first registered provider, in
   OpenAI → Anthropic → Gemini → Grok order.

Unqualified ids are assigned to OpenAI when OpenAI is registered, otherwise to
the first registered provider. Unqualified names beginning with `claude-`,
`gemini-`, or `grok-` are assigned to those providers in the server. `default_model_id()`
raises if no credential is set.

## Streaming contract

Providers translate streamed text, reasoning, tool calls, usage, completion,
and retry signals (429, SSL MAC, 5xx, connection) into `StreamEvent`. OpenAI
selects Responses or Chat Completions from the catalog (with an `o1` / `o3` /
`o4` fallback). Anthropic uses Messages. Gemini uses streamGenerateContent.
Grok uses Chat Completions.

## Model catalog

The shipped catalog in `src/core_ai/models/generated.py` is a checked-in
snapshot produced by the maintainer script `scripts/generate_models.py`.
Installing or building the package ships the snapshot unchanged; nothing
contacts the network at install time.

- Source of ids: the curated [models.dev](https://models.dev) catalog
  (`https://models.dev/api.json`).
- Only text-output models with tool-calling support are emitted for OpenAI,
  Anthropic, Gemini, and Grok.
- Refresh explicitly and commit the result:

```sh
cd core_ai
uv run python scripts/generate_models.py
```

- `CORE_AI_GENERATE_STRICT=1` makes the script fail instead of keeping the
  old snapshot when models.dev is unreachable. `CORE_AI_MODELS_DEV=0` skips
  the network; `MODELS_DEV_URL` points at a mirror.
- `CORE_AI_REFRESH_CATALOG=1` at build time opts a single build into a strict
  refresh through the Hatch hook. Default builds never refresh.

```python
from core_ai import ModelInfo, get_model, list_models
from core_ai.models import register_model

model = get_model("openai", "gpt-4.1")
register_model(ModelInfo(id="local-model", provider="local", api="responses"))
```

Provider credentials: [Environment](../reference/environment.md).
