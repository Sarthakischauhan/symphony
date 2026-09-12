# symphony-harness

`symphony-harness` is a provider-independent, asynchronous agent loop. It runs
a model with Python tools, maintains the conversation for each run, reports
lifecycle events, and applies operational limits and context-window policies.

> The package is under active development (0.1.0). The public API is exported
> from the `core_harness` Python module.

```sh
uv add symphony-harness
```

Docs: **[symphony-harness](../docs/packages/symphony-harness.md)** ·
[Control-plane events](../docs/developer-guide/events.md) ·
[Architecture](../docs/developer-guide/architecture.md)

When using the workspace checkout, install with `uv sync` and run commands
from the repository root or from this directory.

## Quick start

The following is a complete, editable example. Set any supported provider key,
then replace `read_file` or add more tools for your application:

```python
# example.py
import asyncio
from pathlib import Path

from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, HarnessConfig, EventSink, Tool


WORKSPACE = Path(".")


def read_file(path: str) -> str:
    """Read a UTF-8 text file from the configured workspace."""
    target = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in target.parents and target != WORKSPACE.resolve():
        raise ValueError("path must stay inside the workspace")
    return target.read_text(encoding="utf-8")


async def main() -> None:
    registry = build_default_registry()

    # EventSink records events in memory. Subclass emit() for a UI.
    sink = EventSink()
    harness = CoreHarness(
        registry=registry,
        model_id=default_model_id(registry),
        system_prompt="You are a concise assistant. Use tools when they help.",
        config=HarnessConfig(
            max_turns=8,
            max_tool_calls=12,
            max_runtime_seconds=120,
            max_tokens=8_000,
            tool_result_max_chars=4_000,
            context_target_tokens=80_000,
        ),
        tools=[Tool(read_file)],
        sink=sink,
        session_id="example-session",
    )

    result = await harness.run(
        "Inspect README.md and summarize the project in three bullet points."
    )
    print(result.output_text)
    print(f"tool calls: {len(result.tool_calls)}")
    print(f"tokens used: {result.usage.total_tokens}")

    # Every emitted event is available for logging, metrics, or a UI.
    for event in sink.events:
        print(event.event_type, event.payload)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it with:

```sh
ANTHROPIC_API_KEY=your-key-here uv run python example.py
```

`build_default_registry()` recognizes OpenAI, Anthropic, Gemini, Grok, Ollama
(opt-in), and local OpenAI-compatible servers (`LOCAL_BASE_URL`). `model_id` must use the form `provider:model-name`, and that
provider must be registered before calling `run`. You can also construct
`ModelRegistry` manually and register any `BaseProvider` implementation under
a matching namespace.

## Tools

Wrap synchronous or asynchronous Python callables with `Tool`. The callable's
name, docstring, signature, and basic type annotations are used to create the
model-facing schema. For full control, provide `name`, `description`, and/or
an explicit JSON-schema `parameters` object.

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

A tool may declare a `sink` parameter. The harness supplies the
active control plane automatically; it is not exposed as a model argument:

```python
def approve(action: str, sink: EventSink) -> str:
    """Record an approval request."""
    return f"Approved {action}"  # application code can also inspect/emit events
```

Tool results are bounded to 4,000 characters at insert time (40/60 head/tail)
before being persisted. Image parts in a tool result are not
character-truncated. Configure `tool_result_max_chars` on `CoreHarness`, or
pass `None` to disable the bound. Values below 1 are rejected. Truncation
stays in memory: the bounded text is what is stored, and the original payload
is discarded.

History stays linear until the estimated prompt reaches
`tool_result_prune_tokens` (off by default). Only then are older tool bodies
replaced with a path-aware one-line stub on a **copy** of the conversation —
persisted history is unchanged. Unconditional last-N pruning made the model
re-read files it had already seen.

## Runs, results, and conversations

`await harness.run(user_input)` accepts a string or a list of canonical
text/image parts. It returns a `HarnessResult` containing:

- `output_text` — the assistant's final text
- `messages` — messages accumulated during the run
- `tool_calls` — tool calls made during the run
- `usage` — prompt, completion, reasoning, and total token counts
- `context_limit` and `context_left` — provider context information when
  available

A conversation can be supplied explicitly, and a session can be selected per
run:

```python
result = await harness.run(
    "Continue from our previous discussion.",
    conversation=previous_messages,
    session_id="customer-42",
)
```

By default, `NullPersistence` discards state. Attach a `PersistenceAddon` with
an implementation of the `Persistence` protocol to save and load conversation
messages and `Checkpoint` objects as the run progresses. `session_id` is the
key used by persistence. `CoreHarness` does not invent a store on its own.

## Limits and cancellation

Pass a `HarnessConfig` (or a JSON file path) to `CoreHarness`. There is no
packaged defaults file; omitted keys use the `HarnessConfig` field defaults.
Shared product config files may put these values under a top-level `harness`
object.

```python
from core_harness import HarnessConfig, load_harness_config

harness = CoreHarness(
    registry=registry,
    model_id=default_model_id(registry),
    system_prompt="Be helpful.",
    config=HarnessConfig(
        max_turns=6,
        max_tool_calls=10,
        max_runtime_seconds=60,
        max_tokens=4_000,
    ),
)
# or: config=load_harness_config("harness.json")
```

The harness raises `HarnessCancelled` when the run task is cancelled and
`HarnessLimitExceeded` when a configured limit is reached. Cancel a run by
cancelling the `asyncio.Task` that is awaiting `CoreHarness.run`.

## Events

The harness emits run, turn, text/reasoning stream, model-retry, tool, usage,
context, compaction, injection, cancellation, limit, and subagent lifecycle
events. Every harness event name is a member of `ControlPlaneEventType`;
product add-ons (for example the coding agent's `run_summary`) may emit
additional string event types through the same sink. `EventSink` records
events in memory and is the default (`EventSink` is an alias).

The catalog with payload examples is in
[docs/developer-guide/events.md](../docs/developer-guide/events.md) and
[docs/events.md](./docs/events.md).

`EventSink` is an event sink (`emit`) plus an optional
`request_user_input` for product tools such as `ask_user`. It does not
authorize tools, cancel runs, persist, compact, or spawn. The harness stamps
`run_id`, `session_id`, `seq`, `ts`, `schema_version`, `agent_id`, and
`parent_id` on every event. Tools run unless a `before_tool` add-on returns
a deny reason.

## Add-ons

`CoreHarness` is an extension surface. It does not auto-build compaction,
persistence, telemetry, or a spawn tool. Pass `addons=[...]` or call
`register_addon`. Duplicate `name` values raise. Subclass `Addon` for
no-op `before_run`, `before_turn`, `before_tool`, `after_turn`, `on_tool`,
and `on_compact` hooks.
`fork_for_child` is the only inherit path onto a child harness; the
default returns `None`. Skills can use this same attach path later;
there is no directory discovery or loader.

`coding_agent` attaches `PersistenceAddon` (JSONL), its own
`AiCompactionAddon` (an `InferenceCompactor` built on `plan_keep_drop`), and
`SubagentAddon` by default; it does not mount `KeepSystemRecentCompactor`. A
bare harness run has no compaction and no `spawn_agent` tool.

## Subagents

`CoreHarness.spawn()` starts a child run. Parent/child identity (`agent_id`,
`parent_id`), `spawn_depth` / `max_spawn_depth`, and lifecycle events
(`agent_spawned` / `agent_completed` / `agent_failed`) stay on the harness
via `begin_child` / `run_child`. `SubagentAddon` builds the child
`CoreHarness` (tools, config copy, system prompt, turns, add-ons) and
formats the `spawn_agent` tool result. The child run itself uses
`child_config.sink` when provided, otherwise the parent's plane.

Children collect add-ons by calling `fork_for_child` on each parent add-on
(or `ChildConfig.addons` / `ChildConfig.addon_factory` when set). Compaction
and telemetry fork to new instances. Persistence and subagent do not, so
children keep `NullPersistence` and cannot spawn further agents. Parallel
children never share those forked instances.

The `spawn_agent` tool is an add-on. Attach `SubagentAddon` (coding_agent
does this by default). A bare `CoreHarness` has no spawn tool.

```python
from core_harness import ChildConfig, CoreHarness, SubagentAddon, Tool

parent = CoreHarness(
    ...,
    addons=[SubagentAddon()],
)
result = await parent.spawn(
    "Inspect README.md",
    label="readme",
    child_config=ChildConfig(model_id="openai:gpt-5.6-mini", max_turns=4),
)
```

`SubagentAddon(configure=...)` lets a product map model arguments onto a
`ChildConfig` — for example a forked UI control plane that auto-approves child
tools. Children get a fresh conversation, `NullPersistence`, and the parent
tool set minus `spawn_agent`. Nested spawns stop at `max_spawn_depth`.
Multiple `spawn_agent` calls in one turn run concurrently up to the configured
parallel-tool limit. `SubagentAddon(background=True)` returns child IDs immediately;
the runtime delivers results between model turns and waits for unfinished children
before final completion. Hosts await `shutdown_children()` when shutting down.
See [background children](docs/background-children.md) for lifecycle and persistence.

`coding_agent` enables background spawning and supplies persistence and compaction
add-ons for each child, using separate sessions in the parent's storage backend.

## Context management

The harness includes token-estimation helpers. Set `context_limits`,
`context_warn_threshold`, `context_compact_threshold`,
`context_target_tokens`, `tool_result_keep_recent`, and
`tool_result_prune_tokens` on `HarnessConfig`. Attach a `CompactionAddon` when
a run should compact; provide a custom `Compactor` for application-specific
summarization.

`KeepSystemRecentCompactor` keeps the leading system prompt, the original
user task, and the most recent messages. Assistant/tool groups stay together
so the provider protocol stays valid. Dropped messages become one summary
message instead of disappearing. A one-user N-tool loop is not one
un-droppable turn: earlier tool groups can be summarised while the last
`keep_recent` messages stay. Old tool bodies inside kept messages are stubbed
only if the compact is still over the token target. `keep_recent` counts
messages, not conversation turns.

The summary is a deterministic path-aware template; the harness never calls a
provider. The keep/drop rule itself is exported as `plan_keep_drop`, which
returns a `KeepDropPlan` (`leading`, `dropped`, `kept`, plus `assemble(summary)`
and `template_summary()`). A product that wants a model-written summary
implements its own `Compactor` on top of that planner (coding_agent's
`InferenceCompactor` does this) instead of subclassing
`KeepSystemRecentCompactor`. `HarnessState.compact` runs whichever compactor is
mounted on demand and emits the same `compaction_*` events as the per-turn
trigger, so a manual "compact now" surface stays orchestration:

```python
from core_harness import CompactionAddon, HarnessConfig, KeepSystemRecentCompactor

harness = CoreHarness(
    registry=registry,
    model_id=default_model_id(registry),
    system_prompt="Be concise.",
    config=HarnessConfig(
        context_target_tokens=20_000,
        tool_result_keep_recent=8,
        tool_result_prune_tokens=48_000,
        context_compact_threshold=16_000,
        compaction_keep_recent=10,
    ),
    addons=[CompactionAddon(KeepSystemRecentCompactor(keep_recent=10, target_tokens=20_000))],
)
```

## Public building blocks

The package exports the main types needed to integrate the harness:

`Addon`, `Addon`, `PersistenceAddon`, `CompactionAddon`,
`SubagentAddon`, `CoreHarness`, `ChildConfig`, `ChildIdentity`, `Tool`, `HarnessResult`,
`HarnessConfig`, `RunLimits`, `UsageTotals`, `Checkpoint`, `Persistence`,
`NullPersistence`, `Compactor`, `KeepSystemRecentCompactor`, `KeepDropPlan`,
`plan_keep_drop`, `ContextReport`,
`build_context_report`, `bound_tool_result`, `messages_for_model`,
`prune_stale_tool_results`, `EventSink`, `ControlPlaneEvent`,
`ControlPlaneEventType`, `EventSink`, `EventSink`,
`HarnessCancelled`, `HarnessLimitExceeded`, and `load_harness_config`.

## Development

Run tests from this package directory:

```sh
uv run pytest
```
