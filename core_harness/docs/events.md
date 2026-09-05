# Harness events

Canonical user-facing catalog:
**[docs/developer-guide/events.md](../../docs/developer-guide/events.md)**.

`CoreHarness` emits ordered control-plane events with an `event_type` and a
`payload`. Every `event_type` below is a member of
`core_harness.ControlPlaneEventType` except `run_summary`, which is a product
event emitted by the `symphony-code` learning add-on. Events marked conditional
are emitted only when applicable. Identity fields (`run_id`, `session_id`,
`seq`, `ts`, `schema_version`, `agent_id`, `parent_id`) are added by
`IdentifiedControlPlane` and omitted from the examples.

## `run_started`

```json
{
  "event_type": "run_started",
  "payload": {
    "model_id": "anthropic:claude-sonnet-5",
    "tool_names": ["get_weather"],
    "session_id": "session-123"
  }
}
```

## `turn_started`

```json
{
  "event_type": "turn_started",
  "payload": {
    "turn": 0,
    "message_count": 2
  }
}
```

## `text_delta`

```json
{
  "event_type": "text_delta",
  "payload": {
    "turn": 0,
    "delta": "Hello"
  }
}
```

## `reasoning_delta`

```json
{
  "event_type": "reasoning_delta",
  "payload": {
    "turn": 0,
    "summary_index": 0,
    "delta": "I should check the weather.",
    "text": "I should check the weather."
  }
}
```

## `model_retry_scheduled` (conditional)

Emitted when a provider keeps the current turn alive after a retryable rate
limit, SSL MAC error, server, connection, or in-stream error. Providers honor
`Retry-After` and otherwise use capped exponential backoff. Hard errors are
retried up to three times. When `resets_stream` is true, consumers should
discard partial output from the failed attempt.

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

## `tool_call_started`

```json
{
  "event_type": "tool_call_started",
  "payload": {
    "turn": 0,
    "tool_call_id": "call-123",
    "tool_name": "get_weather"
  }
}
```

## `tool_call_delta`

```json
{
  "event_type": "tool_call_delta",
  "payload": {
    "turn": 0,
    "tool_call_id": "call-123",
    "delta": "{\"city\": \"San Francisco\"}"
  }
}
```

## `usage`

```json
{
  "event_type": "usage",
  "payload": {
    "turn": 0,
    "prompt_tokens": 23,
    "completion_tokens": 84,
    "reasoning_tokens": 0,
    "total_tokens": 107,
    "cumulative_tokens": 107,
    "estimated": false
  }
}
```

## `turn_completed`

```json
{
  "event_type": "turn_completed",
  "payload": {
    "turn": 0,
    "had_tool_calls": true
  }
}
```

## `context`

```json
{
  "event_type": "context",
  "payload": {
    "turn": 0,
    "context_limit": 400000,
    "tokens_used": 23,
    "estimated_message_tokens": 12,
    "context_left": 399977,
    "utilization": 0.0000575,
    "message_sizes": [
      {
        "role": "system",
        "index": 0,
        "tokens": 6
      },
      {
        "role": "user",
        "index": 1,
        "tokens": 13
      }
    ]
  }
}
```

## `context_warning` (conditional)

```json
{
  "event_type": "context_warning",
  "payload": {
    "turn": 0,
    "context_limit": 400000,
    "tokens_used": 360000,
    "context_left": 40000,
    "threshold": 50000
  }
}
```

## `tool_execution_started` (conditional)

```json
{
  "event_type": "tool_execution_started",
  "payload": {
    "tool_call_id": "call-123",
    "tool_name": "get_weather",
    "arguments": {
      "city": "San Francisco"
    }
  }
}
```

## `tool_execution_completed` (conditional)

```json
{
  "event_type": "tool_execution_completed",
  "payload": {
    "tool_call_id": "call-123",
    "tool_name": "get_weather",
    "result": "Sunny, 18°C",
    "truncated": false,
    "original_chars": 12
  }
}
```

## `compaction_started` (conditional)

```json
{
  "event_type": "compaction_started",
  "payload": {
    "turn": 3,
    "message_count": 18,
    "tokens_used": 360000,
    "context_left": 40000,
    "threshold": 50000
  }
}
```

## `compaction_completed` (conditional)

```json
{
  "event_type": "compaction_completed",
  "payload": {
    "turn": 3,
    "message_count_before": 18,
    "message_count_after": 4,
    "estimated_tokens_before": 360000,
    "estimated_tokens_after": 24000,
    "context_limit": 400000
  }
}
```

A user-requested compact (for example `/compact` in the TUI) adds
`"manual": true` to both `compaction_started` and `compaction_completed`.
Surfaces can re-derive `tokens_used` / `context_left` from
`estimated_tokens_after` and `context_limit` without waiting for the next
`context` event.

## `paused` (conditional)

```json
{
  "event_type": "paused",
  "payload": {
    "turn": 1
  }
}
```

## `resumed` (conditional)

```json
{
  "event_type": "resumed",
  "payload": {
    "turn": 1
  }
}
```

## `message_injected` (conditional)

```json
{
  "event_type": "message_injected",
  "payload": {
    "turn": 1,
    "role": "user",
    "content": "Use metric units."
  }
}
```

## `run_completed`

```json
{
  "event_type": "run_completed",
  "payload": {
    "turn": 1,
    "output_text": "It is sunny in San Francisco.",
    "usage": {
      "prompt_tokens": 200,
      "completion_tokens": 84,
      "reasoning_tokens": 0,
      "total_tokens": 284
    },
    "context": {
      "context_limit": 400000,
      "tokens_used": 200,
      "context_left": 399800,
      "utilization": 0.0005,
      "message_sizes": []
    },
    "session_id": "session-123"
  }
}
```

## `run_summary` (conditional)

Emitted by a product add-on after `run_completed` when a two-line recap of
the run is available. The coding agent shows this in the transcript as
**summary so far**.

```json
{
  "event_type": "run_summary",
  "payload": {
    "label": "summary so far",
    "summary": "Patched the retry helper.\\nAdded after-run learning recap."
  }
}
```

## `run_cancelled` (conditional)

```json
{
  "event_type": "run_cancelled",
  "payload": {
    "turn": 1,
    "reason": "cancelled"
  }
}
```

## `run_limit_exceeded` (conditional)

Emitted instead of `run_completed` when a `HarnessConfig` cap (`max_turns`,
`max_tool_calls`, `max_runtime_seconds`, `max_tokens`) is reached. The run
raises `HarnessLimitExceeded`.

```json
{
  "event_type": "run_limit_exceeded",
  "payload": {
    "turn": 8,
    "limit": "max_turns",
    "value": 9,
    "max": 8.0,
    "message": "Harness exceeded max_turns=8"
  }
}
```

## `run_failed` (conditional)

```json
{
  "event_type": "run_failed",
  "payload": {
    "turn": 1,
    "error_type": "RuntimeError",
    "message": "provider returned an unexpected payload"
  }
}
```

## `agent_spawned` (conditional)

The payload also includes `tool_call_id`, `child_session_id`,
`parent_session_id`, `max_turns`, and `reasoning_effort` for exact child routing.

Subagent lifecycle events are emitted on the parent's plane. The child's own
events carry the child's `agent_id` and the parent's id as `parent_id`.

```json
{
  "event_type": "agent_spawned",
  "payload": {
    "child_id": "run-child-1",
    "label": "readme",
    "prompt": "Inspect README.md",
    "model_id": "openai:gpt-5.6-mini",
    "depth": 1
  }
}
```

## `waiting_for_children` (conditional)

Emitted when the parent finishes independent work while background children
remain active. Payload: `turn` and `child_ids`. The runtime waits for a child
completion, cancellation, or its deadline, then delivers results through
`message_injected` (`source: "subagent"`) before the next model turn. Waiting
does not invoke a model tool. Parent `run_completed` follows final synthesis.

## `agent_completed` (conditional)

Emitted on the parent's plane when a child finishes.

```json
{
  "event_type": "agent_completed",
  "payload": {
    "child_id": "run-child-1",
    "label": "readme",
    "output_text": "README describes a four-package agent harness.",
    "usage": {
      "prompt_tokens": 400,
      "completion_tokens": 60,
      "reasoning_tokens": 0,
      "total_tokens": 460
    }
  }
}
```

## `agent_failed` (conditional)

```json
{
  "event_type": "agent_failed",
  "payload": {
    "child_id": "run-child-1",
    "label": "readme",
    "message": "Harness exceeded max_turns=4",
    "error_type": "HarnessLimitExceeded"
  }
}
```
