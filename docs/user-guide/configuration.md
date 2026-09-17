# Configuration

Starting a coding agent writes a complete settings file to
`~/.symphony/config.json`. That file is the source of truth for the
spawn. There is no packaged defaults JSON. If the file is missing, spawn
generates it from `CodingAgentConfig` field defaults.

Pass the settings path or a loaded `CodingAgentConfig` into `CodingAgent` /
`CoreHarness`. Constructors do not take a long list of config kwargs.

See [`coding_agent/config.example.json`](../../coding_agent/config.example.json)
for the user-facing shape.

Coding agents have no turn, tool-call, runtime, or token limit by default.
Existing settings still apply; set `harness.max_turns`, `harness.max_tool_calls`,
`harness.max_runtime_seconds`, and `harness.max_tokens` to `null` to disable them.

## Example file

```json
{
  "harness": {
    "max_parallel_tool_calls": 3,
    "max_spawn_depth": 1,
    "context_warn_threshold": 32000,
    "context_compact_ratio": 0.8,
    "context_target_tokens": 80000,
    "compaction_keep_recent_tools": 32,
    "tool_result_max_chars": 32000
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
  },
  "compaction": {
    "max_output_tokens": 700,
    "max_transcript_chars": 24000
  }
}
```

## Approvals

- `ask` — interactive gates for bash, overwrite, and broad patches.
- `always_allow` — every tool call is authorized without a prompt.
- Rules live in `coding_agent.approvals`; the TUI only renders the question.
- TUI **Always allow** is per-run, including child agents, and does not persist.

## Context policy

coding_agent attaches AI compaction (`InferenceCompactor`) by default. When a
prompt reaches 80% of the active model's context limit, it keeps the system prompt, the
original task, and the latest tool groups (the same keep/drop rule as
the harness template compactor). Dropped messages are summarized by the active
model into one compacted-context message that also lists the tools used and
paths already observed; if the model call fails, the template summary is used
for that slice instead. `/compact` runs the same compactor on demand and
refreshes the footer's context meter. `compaction.max_output_tokens` and
`compaction.max_transcript_chars` bound the summary request. The 80,000-token
`context_target_tokens` is the desired post-compaction size. Tool results are
capped at 32,000 characters when they enter history. Older tool bodies remain
visible to the model until compaction.

A bare `CoreHarness` does not compact until a product attaches the add-on.
Set `context_compact_ratio` to `null` to disable auto-compact. `/reload`
rebuilds the provider registry and model choices from `.env` and stored
OAuth tokens. `/provider` writes a key into `~/.symphony/.env` or a
subscription token into `~/.symphony/oauth/`, then reloads so `/model`
lists the new catalog.

The TUI reads colors and CSS from `~/.symphony/theme.toml` when that file
exists. If it is missing, the packaged default dark theme is used. Copy
`coding_agent/tui/theme/theme.toml` to `~/.symphony/theme.toml` to edit.

Skills are discovered from `~/.symphony/skills/` and the workspace's
`.symphony/skills/` directory, followed by any configured skill roots. Plugins
are discovered from `~/.symphony/plugins/<name>/` and the workspace's
`.symphony/plugins/<name>/` directory when plugins are enabled. Each plugin
must contain a `plugin.json` manifest; its `skills` entries are loaded without
executing code. Plugin add-ons remain disabled unless their root is explicitly
listed in `SYMPHONY_PLUGIN_AUTHORIZED_ROOTS`.

This gives installed extensions predictable user/repository scopes while
keeping executable plugin code behind an explicit trust boundary.


## Harness-only config

Library users can pass `HarnessConfig` directly, or
`load_harness_config("harness.json")`. Shared product files may nest these
values under a top-level `harness` object.
