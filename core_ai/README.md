# core-ai

Small shared package for model providers and streaming response types. It is under active construction, so the README stays intentionally brief.

## What it provides

- `ModelRegistry` for routing `provider:model` requests
- `OpenAIProvider` for streaming Chat Completions responses
- `Message` and `StreamEvent` as shared data types

## Example

`core-ai` is used by the coding agent stack:

```python
from core_ai import ModelRegistry, OpenAIProvider
from coding_agent import CodingAgent

registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

agent = CodingAgent(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    workspace=".workspace",
)

result = await agent.run("Create hello.txt with hi, then read it back.")
print(result.output_text)
```

## Development

Run tests from this package directory:

```sh
uv run pytest
```
