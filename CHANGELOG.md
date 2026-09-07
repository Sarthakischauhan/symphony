# Changelog

## 0.1.0 — first public release

Three packages on PyPI: `symphony-core`, `symphony-harness`, `symphony-code`.
`core-server` stays in the workspace and is not published.

### symphony-core

- OpenAI (Responses and Chat Completions, plus `gpt-image-*`), Anthropic
  Messages, Gemini `streamGenerateContent`, Grok Chat Completions.
- Shared `Message` / `StreamEvent` contract, including `reasoning_delta` and
  retry on 429, SSL MAC, 5xx, and connection errors.
- Checked-in model catalog from models.dev. Install and build do not refresh it.

### symphony-harness

- Multi-turn tool loop with run caps (turns, tools, runtime, tokens).
- Control plane: observe events, drive cancel/pause/inject, authorize tools.
  One object, three jobs. Persistence, compaction, and spawn are add-ons.
- `EventControlPlane` is the unattended default (record events, allow tools).
  Interactive products replace it with a plane that asks.
- Subagents, parallel tool calls, keep/drop compaction planner.

### symphony-code

- Workspace tools: `read_file`, `write_file`, `patch`, `search`, `bash`,
  `generate_image`, `ask_user`, `spawn_agent`.
- Textual TUI, plan mode, JSONL sessions under `.symphony/sessions/`.
- Approval policy lives in `coding_agent.approvals`; the TUI only renders the
  question. Children still run without per-tool prompts (see `SECURITY.md`).
- Post-run learning into `.symphony/learning/lessons.jsonl`.

### Known limits in 0.1.0

- Compaction still rewrites the stored conversation. The user-facing TUI hides
  compacted context; a later change will keep the full log and project a
  compact view to the model.
- No skill/plugin loader. Add-ons are attached in Python.
- Learning is a bounded lesson log, not durable retrieval memory.
- `core-server` has no authentication and does not answer `ask_user`.
- File tools are not jailed to the launch directory. Relative paths start
  there; absolute and `~` paths are allowed. `bash` is not a sandbox.
