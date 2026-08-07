## coding_agent

Minimal coding product built on `core_harness`.

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

Conversation persistence is managed under <workspace>/.symphony/sessions.sqlite3, allowing resuming of sessions using `session_id` or the TUI `--resume` command. and can be
resumed by `session_id` or the TUI `--resume` flow.
