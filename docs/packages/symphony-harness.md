# symphony-harness

`symphony-harness` runs a model with Python tools, keeps the conversation for
each run, emits a typed control-plane stream, and applies operational limits.
It does not know about files, terminals, or TUIs.

```sh
uv add symphony-harness
```

Import it as `core_harness`. It depends on `symphony-core`. The full API
surface is listed in the [package README](../../core_harness/README.md).

## Quick start

```python
import asyncio
from pathlib import Path
from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, HarnessConfig, NullControlPlane, Tool

WORKSPACE = Path(".")

def read_file(path: str) -> str:
    """Read a UTF-8 text file from the configured workspace."""
    target = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in target.parents and target != WORKSPACE.resolve():
        raise ValueError("path must stay inside the workspace")
    return target.read_text(encoding="utf-8")

async def main() -> None:
    registry = build_default_registry()
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,
        model_id=default_model_id(registry),
        system_prompt="You are a concise assistant. Use tools when they help.",
        config=HarnessConfig(max_turns=8, max_tool_calls=12, max_runtime_seconds=120),
        tools=[Tool(read_file)],
        control_plane=control_plane,
        session_id="example-session",
    )
    result = await harness.run("Inspect README.md and summarize it in three bullets.")
    print(result.output_text)
    for event in control_plane.events:
        print(event.event_type)

asyncio.run(main())
```

## Tools

Wrap sync or async callables with `Tool`. The name, docstring, signature, and
annotations become the model-facing schema. Override `name`, `description`, or
JSON-schema `parameters` when you need full control.

```python
async def search_docs(query: str, limit: int = 5) -> list:
    """Search the application documentation."""
    return await my_search_backend(query, limit=limit)

harness.register_tool(
    Tool(
        search_docs,
        name="search_docs",
        description="Search internal documentation and return matching pages.",
    )
)
```

A tool may declare a `control_plane` parameter. The harness injects the active
plane; it is not a model argument. Tool results are bounded to 4,000 characters
at insert time (40/60 head/tail) unless you set `tool_result_max_chars=None`.

## Runs and results

`await harness.run(user_input)` accepts a string or a list of canonical
text/image parts. It returns `HarnessResult` with `output_text`, `messages`,
`tool_calls`, `usage`, and context fields. Pass `conversation=` and
`session_id=` to continue a previous run. Default persistence is
`NullPersistence`.

## Subagents

`CoreHarness.spawn()` starts a child run. Lifecycle events stay on the parent
plane. Every child event is stamped with the child's `agent_id` and the
parent's id as `parent_id`. Multiple `spawn_agent` calls in one turn run
concurrently (up to three). Nested spawns stop at `max_spawn_depth`.

```python
from core_harness import ChildConfig

parent.register_tool(parent.make_spawn_tool())
result = await parent.spawn(
    "Inspect README.md",
    label="readme",
    child_config=ChildConfig(model_id="openai:gpt-5.6-mini", max_turns=4),
)
```

## Limits and cancellation

Pass a `HarnessConfig` or a JSON file path. The harness raises
`HarnessCancelled` on cancel and `HarnessLimitExceeded` when a cap is hit.
Inbound commands: pause, resume, inject a message, cancel.

```python
from core_harness import ControlCommand

await control_plane.send_command(ControlCommand.pause())
await control_plane.send_command(ControlCommand.resume())
await control_plane.send_command(ControlCommand.cancel("user stopped the run"))
```

## Control planes

- `NullControlPlane` — records events, accepts inbound commands. Default.
- `InteractiveControlPlane` — optional subscribers / event log.
- `FanoutControlPlane` — send to multiple planes in order.
- `PersistingControlPlane` — appends to an `EventLog`.
- `IdentifiedControlPlane` — stamps `run_id`, `session_id`, `agent_id`,
  `parent_id`, seq, ts, schema version.

Observation-only integrations implement `emit(event_type, payload)`.
Interactive planes can implement `request_user_input` and `approve_tool_call`.
The full catalog is on [Control-plane events](../developer-guide/events.md).

## Context

Compaction is an add-on. Attach `CompactionAddon` / `KeepSystemRecentCompactor`
when a product run should compact. A bare `CoreHarness` does not. coding_agent
attaches keep-system-recent compaction by default. Dropped work becomes a
path-aware summary. coding_agent auto-compacts when 16,000 or fewer context
tokens remain. Disable with `context_compact_threshold=None` (and
`context_target_tokens=None` if you also use a token target).
