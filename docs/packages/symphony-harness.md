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
`NullPersistence`. `Persistence.append_event` is the event journal.

## Subagents

`CoreHarness.spawn()` starts a child run. Parent/child identity stays on the
harness (`begin_child` / `run_child`). `SubagentAddon` builds the child
harness and picks child add-ons via `fork_for_child` (or
`ChildConfig.addons` / `addon_factory`). Lifecycle events stay on the parent
plane. Every child event is stamped with the child's `agent_id` and the
parent's id as `parent_id`. Multiple `spawn_agent` calls in one turn run
concurrently (up to three). Nested spawns stop at `max_spawn_depth`.

The `spawn_agent` tool comes from `SubagentAddon`. coding_agent attaches it
by default. A bare `CoreHarness` has no spawn tool; `spawn()` raises until
that addon is registered.

```python
from core_harness import ChildConfig, SubagentAddon

parent = CoreHarness(..., addons=[SubagentAddon()])
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
when a bare harness run should compact with a template summary and no provider
call. A bare `CoreHarness` does not compact at all. The harness owns the
keep/drop rule (`plan_keep_drop`: system prompt, pinned task, atomic tool
groups, recent window, token target) and exports it so products can build their
own `Compactor` on it. coding_agent does not mount `KeepSystemRecentCompactor`;
it mounts `AiCompactionAddon`, whose `InferenceCompactor` runs the same
keep/drop plan and then writes the dropped-work summary with the active model.
coding_agent auto-compacts when 16,000 or fewer context tokens remain, and
`/compact` runs the same mounted compactor on demand. Disable with
`context_compact_threshold=None` (and `context_target_tokens=None` if you also
use a token target).
