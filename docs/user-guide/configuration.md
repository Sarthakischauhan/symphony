# Configuration

Starting a coding agent writes a complete settings file to
`<workspace>/.symphony/config.json`. That file is the source of truth for the
spawn. There is no packaged defaults JSON. If the file is missing, spawn
generates it from `CodingAgentConfig` field defaults.

Pass the settings path or a loaded `CodingAgentConfig` into `CodingAgent` /
`CoreHarness`. Constructors do not take a long list of config kwargs.

See [`coding_agent/config.example.json`](../../coding_agent/config.example.json)
for the user-facing shape.

## Example file

```json
{
  "harness": {
    "max_turns": 32,
    "max_tool_calls": 60,
    "max_runtime_seconds": 900,
    "max_parallel_tool_calls": 3,
    "max_spawn_depth": 1,
    "context_warn_threshold": 32000,
    "context_compact_threshold": 16000,
    "context_target_tokens": 80000,
    "compaction_keep_recent": 10,
    "tool_result_max_chars": 4000,
    "tool_result_keep_recent": 8,
    "tool_result_prune_tokens": 48000
  },
  "approvals": {
    "mode": "ask",
    "broad_patch_chars": 400,
    "require_for_bash": true,
    "require_for_overwrite": true,
    "require_for_broad_patch": true
  },
  "tools": {
    "bash": {
      "default_timeout_seconds": 30,
      "max_timeout_seconds": 120,
      "max_output_bytes": 32000
    },
    "read_file": {
      "max_text_bytes": 32000,
      "max_image_bytes": 8000000
    },
    "search": {
      "default_max_results": 100,
      "default_max_line_chars": 240,
      "binary_sniff_bytes": 8192
    }
  },
  "learning": {
    "enabled": true,
    "max_output_tokens": 900,
    "max_lessons": 200,
    "context_limit": 6,
    "context_max_chars": 1400
  }
}
```

## Approvals

- `ask` — interactive gates for bash, overwrite, and broad patches.
- `always_allow` — the control plane authorizes every tool call.
- TUI **Always allow** is per-run, including child agents, and does not persist.

## Context policy

coding_agent attaches keep-system-recent compaction by default. When a model
has 16,000 or fewer context tokens left, it keeps the system prompt, the
original task, and the ten most recent messages. Dropped messages are
summarized with paths already observed. Tool results are capped at 4,000
characters when they enter history. Older tool bodies are stubbed only after
the estimated prompt reaches `tool_result_prune_tokens` (48,000 by default).

A bare `CoreHarness` does not compact until a product attaches the add-on.
Pass `context_compact_threshold=None` (and `context_target_tokens=None` to
also drop the token-target trigger) to disable auto-compact. `/reload`
rebuilds the provider registry and model choices from `.env`. `/provider`
writes a key into `~/.symphony/.env`, then reloads so `/model` lists the new
catalog.


## Harness-only config

Library users can pass `HarnessConfig` directly, or
`load_harness_config("harness.json")`. Shared product files may nest these
values under a top-level `harness` object.
