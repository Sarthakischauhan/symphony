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
- emits control-plane events such as `run_started`, `text_delta`, tool execution, `usage`, and `context`
- estimates usage when the provider omits it, warns when `context_left` is low, and can compact history via a pluggable `Compactor`

### Context management

```python
from core_harness import CoreHarness, KeepSystemRecentCompactor, Tool

harness = CoreHarness(
    registry=registry,
    model_id="openai:gpt-4.1-mini",
    system_prompt="You are a concise assistant.",
    tools=[Tool(get_weather)],
    control_plane=PrintControlPlane(),
    context_warn_threshold=8_000,
    context_compact_threshold=4_000,
    compactor=KeepSystemRecentCompactor(keep_recent=6),
)
```

Extra control-plane events from context management:

- `context_warning` — `context_left` at or below `context_warn_threshold`
- `compaction_started` / `compaction_completed` — history reduced before a turn
- `usage.estimated` — `true` when provider usage was missing and a heuristic was used
- `context.message_sizes` — per-message token estimates for planning/debug

### Control plane product surface

```python
from core_harness import (
    ControlCommand,
    ControlPlaneEventType,
    CoreHarness,
    FanoutControlPlane,
    InMemoryEventLog,
    InteractiveControlPlane,
    PersistingControlPlane,
    Tool,
)

event_log = InMemoryEventLog()
control_plane = InteractiveControlPlane(event_log=event_log)

# or fan out to multiple sinks
control_plane = FanoutControlPlane(
    [InteractiveControlPlane(), PersistingControlPlane(event_log)],
)

# inbound commands (do not overload emit)
await control_plane.send_command(ControlCommand.pause())
await control_plane.send_command(ControlCommand.resume())
await control_plane.send_command(ControlCommand.inject_message(content="Focus."))
await control_plane.send_command(ControlCommand.cancel(reason="user-stop"))
```

Typed event names live in `ControlPlaneEventType` and remain string-compatible with `emit(...)`.

### Layout

- `harness.py` contains `CoreHarness`
- `tools.py` contains callable tool wrapping
- `control_plane.py` contains the control-plane protocol, fan-out, persistence, and inbound commands
- `compaction.py` contains the pluggable compaction protocol
- `tokens.py` contains heuristic token estimation helpers
- `models/harness.py` contains harness result models
- `models/tools.py` contains tool-call models
- `models/control_plane.py` contains control-plane event/command models
