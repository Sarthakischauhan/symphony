# Control-plane events

`CoreHarness` emits ordered control-plane events with an `event_type` and a
`payload`. Every event carries `run_id`, `session_id`, a sequence number,
timestamp, and schema version. Events marked conditional fire only when
applicable. The SSE server forwards these names and bodies unchanged.

Payload examples for every event also live in
[`core_harness/docs/events.md`](../../core_harness/docs/events.md).

## Lifecycle

| Event | When |
| --- | --- |
| `run_started` | A run begins (`model_id`, `tool_names`, `session_id`) |
| `turn_started` | Each model turn (`turn`, `message_count`) |
| `turn_completed` | Turn finished (`had_tool_calls`) |
| `run_completed` | Final text, usage, context, session |
| `run_cancelled` | Cancel command landed (conditional) |
| `run_failed` | Unhandled error or limit (conditional) |

## Stream

| Event | Payload notes |
| --- | --- |
| `text_delta` | `turn`, `delta` |
| `reasoning_delta` | `summary_index`, `delta`, `text` |
| `model_retry_scheduled` | Rate-limit / server retry. Honor `Retry-After`. If `resets_stream`, discard partial output. |
| `usage` | Per-turn and cumulative tokens |

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

| Event | Payload notes |
| --- | --- |
| `tool_call_started` | `tool_call_id`, `tool_name` |
| `tool_call_delta` | Argument JSON delta |
| `tool_execution_started` | `arguments` (conditional) |
| `tool_execution_completed` | `result`, `truncated`, `original_chars` |

## Context

- `context` — limit, tokens used, left, utilization, per-message sizes.
- `context_warning` — crossed `context_warn_threshold`.
- `compaction_started` / `compaction_completed` — before/after counts and estimates.

## Control

- `paused` / `resumed` — inbound pause/resume.
- `message_injected` — user or system message inserted mid-run.
- `agent_spawned` / `agent_completed` / `agent_failed` — child lifecycle on the parent plane.

Over SSE, the same body is sent with `event: text_delta` and
`id: <run_id>:<seq>`.
