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

## spawn_agent

Optional `model_id` and `max_turns` apply to that child only. Children get a
fresh conversation, `NullPersistence`, and the parent tool set minus
`spawn_agent`. Compaction forks to a new add-on instance per child. Nested
spawns stop at `max_spawn_depth` (1 by default).

## Adding a tool

One tool per file, same shape everywhere: subclass `WorkspaceTool`, implement
`run`, register it. Shared base handles working-directory relative paths,
pydantic schemas, and `as_harness_tool()`. There is no path jail.
