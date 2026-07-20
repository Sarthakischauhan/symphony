## core_harness

`core_harness` is a minimal agent loop that combines:

- a `system_prompt`
- a list of registered `Tool` objects
- a `control_plane` that receives lifecycle events

### Prototype surface

```python
from core_ai.registry import ModelRegistry
from core_harness import CoreHarness, Tool


class PrintControlPlane:
    async def emit(self, event_type: str, payload: dict) -> None:
        print(event_type, payload)


def get_weather(city: str) -> str:
    """Return a fake weather response for the requested city."""
    return f"It is sunny in {city}."


registry = ModelRegistry()

harness = CoreHarness(
    registry=registry,
    model_id="openai:gpt-4.1-mini",
    system_prompt="You are a concise assistant.",
    tools=[Tool(get_weather)],
    control_plane=PrintControlPlane(),
)

result = await harness.run("What is the weather in San Francisco?")
print(result.output_text)
```

### What it does

- prepends the configured system prompt
- streams model output through `core_ai.ModelRegistry`
- collects tool calls and executes registered tools
- appends tool responses back into the conversation
- emits control-plane events such as `run_started`, `text_delta`, and tool execution events

### Layout

- `harness.py` contains `CoreHarness`
- `tools.py` contains callable tool wrapping
- `control_plane.py` contains the control-plane protocol and default implementation
- `models/harness.py` contains harness result models
- `models/tools.py` contains tool-call models
- `models/control_plane.py` contains control-plane event models
