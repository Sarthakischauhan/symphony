# core-harness

`core-harness` is a provider-independent, asynchronous agent loop. It runs a model with Python tools, maintains the conversation for each run, reports lifecycle events, and applies operational limits and context-window policies.

> The package is under active development. The public API is exported from `core_harness`.

## Installation

From this repository:

```sh
uv add core-harness
```

When using the workspace checkout, install the workspace dependencies with `uv sync` and run commands from the repository root or from this directory.

## Quick start

The following is a complete, editable example. Set any supported provider key,
then replace `read_file` or add more tools for your application:

```python
# example.py
import asyncio
from pathlib import Path

from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, NullControlPlane, Tool


WORKSPACE = Path(".")


def read_file(path: str) -> str:
    """Read a UTF-8 text file from the configured workspace."""
    target = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in target.parents and target != WORKSPACE.resolve():
        raise ValueError("path must stay inside the workspace")
    return target.read_text(encoding="utf-8")


async def main() -> None:
    registry = build_default_registry()

    # NullControlPlane records events locally and also accepts pause, resume,
    # cancel, and message-injection commands. Use InteractiveControlPlane or
    # FanoutControlPlane when an application needs to forward events elsewhere.
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,
        model_id=default_model_id(registry),
        system_prompt="You are a concise assistant. Use tools when they help.",
        tools=[Tool(read_file)],
        control_plane=control_plane,
        max_turns=8,
        max_tool_calls=12,
        max_runtime_seconds=120,
        max_tokens=8_000,
        tool_result_max_chars=12_000,
        context_target_tokens=80_000,
        session_id="example-session",
    )

    result = await harness.run(
        "Inspect README.md and summarize the project in three bullet points."
    )
    print(result.output_text)
    print(f"tool calls: {len(result.tool_calls)}")
    print(f"tokens used: {result.usage.total_tokens}")

    # Every emitted event is available for logging, metrics, or a UI.
    for event in control_plane.events:
        print(event.event_type, event.payload)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it with:

```sh
ANTHROPIC_API_KEY=your-key-here uv run python example.py
```

`build_default_registry()` recognizes OpenAI, Anthropic, and Gemini credentials.
`model_id` must use the form `provider:model-name`, and that provider must be
registered before calling `run`. You can also construct `ModelRegistry` manually
and register any `BaseProvider` implementation under a matching namespace.

## Tools

Wrap synchronous or asynchronous Python callables with `Tool`. The callable's name, docstring, signature, and basic type annotations are used to create the model-facing schema. For full control, provide `name`, `description`, and/or an explicit JSON-schema `parameters` object.

```python
async def search_docs(query: str, limit: int = 5) -> list:
    """Search the application documentation."""
    return await my_search_backend(query, limit=limit)

harness.register_tool(
    Tool(
        search_docs,
        name="search_docs",
        description="Search internal documentation and return matching pages.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    )
)
```

A tool may declare a `control_plane` parameter. The harness supplies the active control plane automatically; it is not exposed as a model argument:

```python
def approve(action: str, control_plane: NullControlPlane) -> str:
    """Record an approval request."""
    return f"Approved {action}"  # application code can also inspect/emit events
```

Tool results are bounded to 12,000 characters by default before being sent in the next model request. Image parts in a tool result are not character-truncated. Configure `tool_result_max_chars` on `CoreHarness`, or pass `None` to disable the bound. Values below 1 are rejected.

## Runs, results, and conversations

`await harness.run(user_input)` accepts a string or a list of canonical text/image parts. It returns a `HarnessResult` containing:

- `output_text` — the assistant's final text
- `messages` — messages accumulated during the run
- `tool_calls` — tool calls made during the run
- `usage` — prompt, completion, reasoning, and total token counts
- `context_limit` and `context_left` — provider context information when available

A conversation can be supplied explicitly, and a session can be selected per run:

```python
result = await harness.run(
    "Continue from our previous discussion.",
    conversation=previous_messages,
    session_id="customer-42",
)
```

By default, `NullPersistence` discards state. Pass an implementation of the `Persistence` protocol to save and load conversation messages and `Checkpoint` objects as the run progresses. `session_id` is the key used by persistence.

## Subagents

`CoreHarness.spawn()` starts a child run. Lifecycle events (`agent_spawned` / `agent_completed` / `agent_failed`) stay on the parent plane. The child run itself uses `child_config.control_plane` when provided, otherwise the parent's plane. Every child event is stamped with the child's `agent_id` and the parent's id as `parent_id`.

```python
from core_harness import ChildConfig, CoreHarness, Tool

parent.register_tool(parent.make_spawn_tool())
result = await parent.spawn(
    "Inspect README.md",
    label="readme",
    child_config=ChildConfig(model_id="openai:gpt-5.6-mini", max_turns=4),
)
```

`make_spawn_tool(configure=...)` lets a product map model arguments onto a `ChildConfig` — for example a forked UI control plane with its own approval lock. Children get a fresh conversation, `NullPersistence`, and the parent tool set minus `spawn_agent`. Nested spawns stop at `max_spawn_depth`. Multiple `spawn_agent` calls in one turn run concurrently (up to three).

## Limits and cancellation

Engine-owned defaults are loaded from `core_harness/defaults.json`. Applications
can load an override with `load_harness_config(path)` and pass the resulting
`HarnessConfig` to `CoreHarness(config=...)`. Shared product config files may put
these values under a top-level `harness` object.

Configure safeguards either with individual arguments or with a `RunLimits` object:

```python
from core_harness import RunLimits

harness = CoreHarness(
    registry=registry,
    model_id=default_model_id(registry),
    system_prompt="Be helpful.",
    limits=RunLimits(
        max_turns=6,
        max_tool_calls=10,
        max_runtime_seconds=60,
        max_tokens=4_000,
    ),
)
```

The harness raises `HarnessCancelled` when a run is cancelled and `HarnessLimitExceeded` when a configured limit is reached. An inbound control plane can pause, resume, cancel, or inject a user/system message while a run is active:

```python
from core_harness import ControlCommand

await control_plane.send_command(ControlCommand.pause())
await control_plane.send_command(ControlCommand.resume())
await control_plane.send_command(ControlCommand.inject_message(
    role="user", content="Also include the security implications."
))
await control_plane.send_command(ControlCommand.cancel("user stopped the run"))
```

## Events and control planes

The harness emits run, turn, text-stream, tool, usage, context, compaction, pause/resume, injection, cancellation, limit, and subagent lifecycle events. Event types are available as `ControlPlaneEventType` values. `NullControlPlane` records events in memory and is the default.

Available control-plane adapters include:

- `NullControlPlane` — records events and supports inbound commands.
- `InteractiveControlPlane` — records events and optionally forwards them to subscribers or an event log.
- `FanoutControlPlane` — sends events to multiple control planes in order.
- `PersistingControlPlane` — appends events to an `EventLog`.
- `IdentifiedControlPlane` — adds `run_id`, `session_id`, `agent_id`, `parent_id`, sequence, timestamp, and schema-version metadata to each event.
- `InMemoryEventLog` — a simple event-log implementation for tests and local use.

For observation-only integrations, implement the `ControlPlane` protocol's
asynchronous `emit(event_type, payload)` method. Interactive control planes can
also implement `request_user_input(...)` and `approve_tool_call(...)`; the harness
calls the approval gate before invoking a registered tool. Inbound implementations
can additionally implement `send_command` and `drain_commands`.

## Context management

The harness includes token-estimation helpers and compaction support. Configure `context_limits`, `context_warn_threshold`, and `context_compact_threshold` for context monitoring. Set `context_target_tokens` to control the target size after compaction, and provide a custom `Compactor` when application-specific summarization is needed.

`KeepSystemRecentCompactor` is included for a simple policy that preserves the leading system message and the most recent conversation messages while keeping assistant tool-call groups intact:

```python
from core_harness import KeepSystemRecentCompactor

harness = CoreHarness(
    registry=registry,
    model_id=default_model_id(registry),
    system_prompt="Be concise.",
    compactor=KeepSystemRecentCompactor(keep_recent=8),
    context_target_tokens=20_000,
)
```

## Public building blocks

The package exports the main types needed to integrate the harness:

`CoreHarness`, `Tool`, `HarnessResult`, `RunLimits`, `UsageTotals`, `Checkpoint`, `Persistence`, `NullPersistence`, `Compactor`, `KeepSystemRecentCompactor`, `ControlPlane`, `ControlPlaneEvent`, `ControlPlaneEventType`, `ControlCommand`, `ControlCommandType`, `NullControlPlane`, `InteractiveControlPlane`, `FanoutControlPlane`, `PersistingControlPlane`, `IdentifiedControlPlane`, `InMemoryEventLog`, `HarnessCancelled`, and `HarnessLimitExceeded`.

## Development

Run tests from this package directory:

```sh
uv run pytest
```
