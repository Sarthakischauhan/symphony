# Control-plane events

`CoreHarness` emits ordered control-plane events with an `event_type` and a
`payload`. When the harness runs behind `IdentifiedControlPlane` (the default
inside `CoreHarness.run`), every payload also carries `run_id`, `session_id`,
`seq`, `ts`, `schema_version`, `agent_id`, and `parent_id`. Events marked
conditional fire only when applicable. The SSE server forwards these names and
bodies unchanged.

The authoritative list of harness event names is
`core_harness.ControlPlaneEventType` (`core_harness/src/core_harness/models.py`).
The tables below cover every member of that enum. Payload examples for each
event live in [`core_harness/docs/events.md`](../../core_harness/docs/events.md).

## Lifecycle

| Enum member | `event_type` | When |
| --- | --- | --- |
| `RUN_STARTED` | `run_started` | A run begins (`model_id`, `tool_names`, `session_id`) |
| `TURN_STARTED` | `turn_started` | Each model turn (`turn`, `message_count`) |
| `TURN_COMPLETED` | `turn_completed` | Turn finished (`had_tool_calls`) |
| `RUN_COMPLETED` | `run_completed` | Final text, usage, context, session |
| `RUN_CANCELLED` | `run_cancelled` | Cancel command landed (conditional; `reason`) |
| `RUN_LIMIT_EXCEEDED` | `run_limit_exceeded` | A `HarnessConfig` cap was hit (conditional; `limit`, `value`, `max`, `message`) |
| `RUN_FAILED` | `run_failed` | Unhandled error (conditional; `error_type`, `message`) |

A run ends with exactly one of `run_completed`, `run_cancelled`,
`run_limit_exceeded`, or `run_failed`.

## Stream

| Enum member | `event_type` | Payload notes |
| --- | --- | --- |
| `TEXT_DELTA` | `text_delta` | `turn`, `delta` |
| `REASONING_DELTA` | `reasoning_delta` | `turn`, `summary_index`, `delta`, `text` (conditional; reasoning models only) |
| `MODEL_RETRY_SCHEDULED` | `model_retry_scheduled` | Rate-limit, SSL MAC, 5xx, or connection retry. Honor `retry_after`. If `resets_stream`, discard partial output. (conditional) |
| `USAGE` | `usage` | Per-turn and cumulative tokens |

```json
{
  "event_type": "text_delta",
  "payload": { "turn": 0, "delta": "Hello" }
}
```

```json
{
  "event_type": "model_retry_scheduled",
  "payload": {
    "turn": 0,
    "retry_after": 2.5,
    "attempt": 1,
    "reason": "rate_limit",
    "resets_stream": false
  }
}
```

## Tools

| Enum member | `event_type` | Payload notes |
| --- | --- | --- |
| `TOOL_CALL_STARTED` | `tool_call_started` | `turn`, `tool_call_id`, `tool_name` |
| `TOOL_CALL_DELTA` | `tool_call_delta` | Argument JSON `delta` |
| `TOOL_EXECUTION_STARTED` | `tool_execution_started` | `tool_call_id`, `tool_name`, `arguments` |
| `TOOL_EXECUTION_COMPLETED` | `tool_execution_completed` | `result`, `truncated`, `original_chars`. A denied or unknown tool still produces both events; the denial is the `result`. |

## Context

| Enum member | `event_type` | Payload notes |
| --- | --- | --- |
| `CONTEXT` | `context` | Limit, tokens used, left, utilization, per-message sizes |
| `CONTEXT_WARNING` | `context_warning` | Crossed `context_warn_threshold` (conditional) |
| `COMPACTION_STARTED` | `compaction_started` | Before-compaction message count and token estimate (conditional) |
| `COMPACTION_COMPLETED` | `compaction_completed` | Before/after counts and estimates, `context_limit` (conditional) |

A user-requested compact (`/compact` in the TUI) adds `"manual": true` to both
compaction events.

## Control

| Enum member | `event_type` | Payload notes |
| --- | --- | --- |
| `PAUSED` | `paused` | Inbound pause command (conditional) |
| `RESUMED` | `resumed` | Inbound resume command (conditional) |
| `MESSAGE_INJECTED` | `message_injected` | User or system message inserted mid-run (`role`, `content`; conditional) |

## Subagents

Emitted on the **parent's** plane when a run spawns a child via
`CoreHarness.spawn()` / the `spawn_agent` tool. The child's own events are
emitted with the child's `agent_id` and the parent's id as `parent_id`.

| Enum member | `event_type` | Payload notes |
| --- | --- | --- |
| `AGENT_SPAWNED` | `agent_spawned` | `child_id`, `label`, `prompt`, `model_id`, `depth` |
| `AGENT_COMPLETED` | `agent_completed` | `child_id`, `label`, `output_text`, `usage` |
| `AGENT_FAILED` | `agent_failed` | `child_id`, `label`, `message`, `error_type` |
| `WAITING_FOR_CHILDREN` | `waiting_for_children` | `turn`, `child_ids` — parent has finished independent work and is waiting for child results |

`agent_spawned` also carries `tool_call_id`, `child_session_id`,
`parent_session_id`, `max_turns`, and `reasoning_effort`. These identify the
originating tool invocation and the child's saved session without matching labels.
Background results arrive between model turns as `message_injected` with
`source: "subagent"`. The runtime waits for outstanding children before emitting
the parent's final `run_completed`; no model-facing polling tool is required.

## Product events (not in the harness enum)

Add-ons and products may emit their own events through the same plane. These
are **not** members of `ControlPlaneEventType`; consumers should treat unknown
`event_type` strings as pass-through.

| `event_type` | Emitted by | Payload notes |
| --- | --- | --- |
| `run_summary` | `symphony-code` learning add-on, after `run_completed` | `label`, `summary` — the two-line **summary so far** shown in the TUI (conditional) |

## Transport

Over SSE (`core-server`), the same body is sent with `event: <event_type>` and
`id: <run_id>:<seq>`.
