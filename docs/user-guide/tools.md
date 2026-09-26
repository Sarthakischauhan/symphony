# Tools

The agent keeps a small tool surface on purpose. Repository context is
discovered incrementally with `search` and `read_file` — there is no preloaded
semantic index in the prompt.

| Tool | What it does |
| --- | --- |
| `read_file` | Bounded UTF-8 text with line numbers, or image files (png/jpeg/gif/webp) as visual content. |
| `write_file` | Create or replace a complete file without stripping whitespace. |
| `generate_image` | Generate png/jpeg/webp via the current OpenAI or Gemini provider, write it, show `[Image 1]`. |
| `patch` | Unique-match exact-text edits. CRLF, trailing whitespace, and curly quotes are folded for matching. |
| `search` | File names or literal/regex content, with path and glob filters. |
| `bash` | Shell in the working directory, streamed, capped, timed out, process-group cleanup. |
| `spawn_agent` | Child harness run. Call more than once in a turn to run up to three children in parallel. |
| `ask_user` | Clarifying questions routed through the control plane. |

## Patch matching

A miss lists nearby lines with whitespace made visible. Identical old/new is
a no-op, not an error. Broad patches (over `approvals.broad_patch_chars`)
require confirmation in `ask` mode.

## Bash

Non-zero exits and timeouts return the captured output; they are not tool
failures. Default timeout 30s, max 120s, output capped at 32 KB.

`background: true` starts the command detached (its own process group, output
to `~/.symphony/sessions/jobs/<job_id>.log`) and returns the job id at once.
It is capped by `tools.bash.max_background_seconds` (default 3600), not the
foreground max. When it exits, one bounded message (exit code, duration, last
~2 KB, log path) is injected before the next turn; the run waits for running
jobs before it completes, so the model never needs to poll. `action: "output"`
tails a job's log, `action: "stop"` kills its process group. Cancelling the run
kills running jobs. The run will not finish while a background job is alive,
so stop it with `action: "stop"` when you are done with it.

## spawn_agent

Optional `model_id` and `max_turns` apply to that child only. Children get a
fresh conversation and a fresh turn budget. When `spawn_max_turns` is set it
caps the child; when unset (product default), children have no turn cliff and
rely on context compaction. Children use `NullPersistence` and the parent tool
set minus `spawn_agent`. Compaction forks to a new add-on instance per child.
Nested spawns stop at `max_spawn_depth` (1 by default).

## Adding a tool

One tool per file, same shape everywhere: subclass `WorkspaceTool`, implement
`run`, register it. Shared base handles working-directory relative paths,
pydantic schemas, and `as_harness_tool()`. There is no path jail.
