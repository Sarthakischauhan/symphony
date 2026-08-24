# Harness events

`CoreHarness` emits ordered control-plane events with an `event_type` and a
`payload`. Events marked conditional are emitted only when applicable.

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

Emitted when a provider keeps the current turn alive after a retryable 429.
OpenAI, Anthropic, and Gemini honor `Retry-After` and use capped exponential
backoff when that header is absent.

```json
{
  "event_type": "model_retry_scheduled",
  "payload": {
    "turn": 0,
    "retry_after": 2.5,
    "attempt": 1,
    "reason": "rate_limit"
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
    "estimated_tokens_after": 24000
  }
}
```

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

## `run_failed` (conditional)

```json
{
  "event_type": "run_failed",
  "payload": {
    "turn": 1,
    "error_type": "RuntimeError",
    "message": "Harness exceeded max_turns=8"
  }
}
```
