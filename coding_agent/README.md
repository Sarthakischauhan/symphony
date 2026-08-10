## coding_agent

A workspace coding agent built on `core_harness`.

### What it provides

- Five workspace tools: `read_file`, `write_file`, `patch`, `search`, and `bash`
- Incremental repository discovery through `search` + `read_file`, without a preloaded repo index
- Persisted conversations in SQLite, resumable by `session_id` or TUI `--resume`
- Optional learning/reflection after successful runs
- A conversation-first Textual TUI with streaming output, tool events, reasoning summaries, usage stats, and context/compaction notices

### Tool surface

The agent intentionally exposes five workspace tools:

- `read_file` reads bounded UTF-8 content.
- `write_file` creates or replaces a complete file without stripping whitespace.
- `patch` performs unique-match exact-text edits.
- `search` finds file names or literal/regex content with path and glob filters.
- `bash` runs workspace-scoped shell commands.

Repository context is discovered incrementally with `search` and `read_file`; the
agent does not parse or preload a semantic repository index.

### Run it

```bash
uv run --package coding-agent coding-agent-tui
uv run --package coding-agent coding-agent-tui --workspace /path/to/project
```

The TUI renders harness events as a conversation: streamed Markdown responses,
live tool rows, reasoning summaries, muted per-turn token usage, context warnings,
compaction notices, persisted session history, and code blocks using the same
muted Symphony palette as the surrounding interface. Use `Ctrl+L` or `/clear` to
reset the visible transcript and `Ctrl+D`, `/quit`, or `/exit` to leave.

Type `/` to discover commands. `/model` shows the built-in model catalog,
`/model <id>` switches the harness and learning model, and `/mode` switches between
build and read-only plan modes. Tab toggles the mode without opening the menu.
Plan mode uses a light-yellow composer and writes streamed plans to readable,
task-named files such as `to_build_a_server_plan.md`. When planning finishes,
the plan opens in a modal with a **Build now** action; `/plan` reopens the latest one.
`/new` starts a new persisted session, `/compact` keeps the system prompt and recent
valid tool-call blocks, `/diff` opens the current workspace diff in a modal,
`/status` displays the current runtime context, `/help` shows commands, and `/clear`
clears the visible transcript.
Model choices currently come from `coding_agent.tui.commands.MODEL_CATALOG`; this
boundary can be replaced with provider-backed registry discovery later.

```python
agent = CodingAgent(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    workspace=".",
)
result = await agent.run("Fix the failing test")
```

### Learning

After a successful run returns, an optional background reflection makes one
structured model call. Useful lessons are appended to:

```text
<workspace>/.symphony/learning/lessons.jsonl
```

Reflection never delays or changes the completed run. Future runs receive only a
small task-relevant selection of lessons. Routine runs can return
`should_save=false`, and reflection failures are logged without affecting the agent.

Disable learning with `enable_learning=False`. Call
`await agent.wait_for_learning()` only when an application needs to drain pending
reflection tasks before shutdown.

Conversation persistence is managed under
`<workspace>/.symphony/sessions.sqlite3`, allowing resuming of sessions using
`session_id` or the TUI `--resume` command.
