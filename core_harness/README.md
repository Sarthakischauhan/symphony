# symphony-harness

A product-agnostic async agent loop for Python: model turns, callable tools, operational limits, and a typed event stream. Import it as `core_harness`.

**Availability:** version 0.0.1 is on PyPI: `pip install symphony-harness`. Import name: `core_harness`. Development still uses the repository workspace; see the [installation guide](../docs/getting-started/installation.md).

## Minimal example

```python
import asyncio
from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, Tool

def read_file(path: str) -> str:
    """Read a UTF-8 file."""
    with open(path, encoding="utf-8") as file:
        return file.read()

async def main() -> None:
    harness = CoreHarness(
        registry=build_default_registry(),
        registry=build_default_registry(),
        model_id=default_model_id(registry),
        system_prompt="Answer concisely and use tools when useful.",
        tools=[Tool(read_file)],
    )
    result = await harness.run("Summarize README.md", session_id="example")
    print(result.output_text)

asyncio.run(main())
```

`CoreHarness` does not provide a filesystem boundary or default approval policy: attach only tools you intend to expose, and add product-level policy where needed. See [SECURITY.md](../SECURITY.md).

## Build with the harness

- [Harness guide](../docs/packages/symphony-harness.md): tools, runs, subagents, limits, and context.
- [Extend the harness](../docs/developer-guide/extending.md): add-on hooks and child behavior.
- [Event overview](../docs/developer-guide/events.md) and [detailed event catalog](docs/events.md).
- [Background child lifecycle](docs/background-children.md).
- [Architecture](../docs/developer-guide/architecture.md).
