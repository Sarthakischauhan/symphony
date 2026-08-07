# core-harness

Minimal agent loop for running a model with tools and a control plane. This package is under active development with key capabilities, including: \n- `CoreHarness` for executing model tools and managing command/event workflows.\n- Various control plane implementations for handling events and logging.\n- `Persistence` protocols for managing conversation state and checkpointing., so the README is intentionally short.

## What it provides

- `CoreHarness` for turn-based agent execution
- `Tool` for wrapping Python callables as model tools
- control-plane primitives for lifecycle events and commands
- `Persistence` protocol for conversation + checkpoint saves (`NullPersistence` default)
- simple compaction and token-estimation helpers

Pass any `Persistence` implementation into `CoreHarness` (or `CodingAgent`); the harness
saves conversation state and turn checkpoints as the run progresses.

## Example

`core-harness` powers the coding agent:

```python
from core_ai import ModelRegistry, OpenAIProvider
from core_harness import CoreHarness, Tool


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

harness = CoreHarness(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    system_prompt="You are a concise coding assistant.",
    tools=[Tool(read_file)],
)

result = await harness.run("Inspect README.md and summarize it.")
print(result.output_text)
```

The coding agent builds on top of this layer to add workspace tools:

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
