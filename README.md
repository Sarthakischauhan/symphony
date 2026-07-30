# Symphony

Monorepo for a small agent stack under active construction.

## What’s here

- [`core_ai`](./core_ai/README.md) - shared model/provider abstractions and streaming types
- [`core_harness`](./core_harness/README.md) - the minimal agent loop and control-plane layer
- [`coding_agent`](./coding_agent/README.md) - workspace-aware coding agent built on top of the harness

## Structure

The stack is intentionally layered:

- `core_ai` handles provider registration and streamed model responses
- `core_harness` turns those streams into an agent loop with tools and control-plane events
- `coding_agent` adds workspace tools and a small TUI on top of the harness

## Quick Start

```sh
export OPENAI_API_KEY=...
uv run --package coding-agent coding-agent-tui
```

The TUI uses `.workspace` by default. To point it elsewhere:

```sh
uv run --package coding-agent coding-agent-tui --workspace /tmp/coding-agent-workspace
```

## Example

The main end-to-end use case is the coding agent:

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

- Run package tests with `uv run pytest` from the package directory.
- Run the coding agent TUI from the repo root with `uv run --package coding-agent coding-agent-tui`.
- Package-specific details live in each package README.

## Status

This repo is still evolving. APIs and layouts may change as the agent stack matures.
