# symphony-harness

A product-agnostic async agent loop for Python. The harness sends conversation turns to a model, runs registered tools, and emits typed events. It does not provide workspace-specific tools, a terminal UI, or a default approval policy.

**Availability:** published on PyPI as version 0.0.1. Install with `pip install symphony-harness`, which also installs `symphony-core`. Import name: `core_harness`. A source checkout is described in [Install Symphony](../getting-started/installation.md).

## Run a tool-enabled agent

```python
import asyncio
from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, HarnessConfig, Tool

def read_text(path: str) -> str:
    """Read a UTF-8 text file."""
    with open(path, encoding="utf-8") as file:
        return file.read()

async def main() -> None:
    registry = build_default_registry()
    harness = CoreHarness(
        registry=registry,
        model_id=default_model_id(registry),
        system_prompt="Answer concisely. Use tools when useful.",
        config=HarnessConfig(),
        tools=[Tool(read_text)],
    )
    result = await harness.run("Summarize README.md")
    print(result.output_text)

asyncio.run(main())
```

This example deliberately exposes a read-only tool. `CoreHarness` runs the tools you register; it does not sandbox them. Add only capabilities your application is prepared to expose.

## Core concepts

- **Tools:** wrap sync or async Python callables with `Tool`; their annotations and docstrings define model-facing inputs. An optional `category` (for example `"search"`) lets a host enable tools in groups.
- **Model calls:** each turn streams from the registry; for a realtime model with an open voice session it streams through that session instead. Pass `model_call=` to `CoreHarness` to supply your own.
- **Runs:** `await harness.run(...)` returns a `HarnessResult`; supply conversation and session state when building a continuing application.
- **Events:** an `EventSink` publishes ordered lifecycle, model, tool, and context events.
- **Add-ons:** attach behavior at run, turn, and tool lifecycle hooks; the harness itself stays independent of product features.
- **Limits and cancellation:** configure bounded runs and cancel the task or submit an interrupt.

## Extend or inspect

- [Add-on hooks](../developer-guide/extending.md)
- [Event overview](../developer-guide/events.md) · [full event catalog](../../core_harness/docs/events.md)
- [Architecture](../developer-guide/architecture.md)
- [Package API and advanced examples](../../core_harness/README.md)
