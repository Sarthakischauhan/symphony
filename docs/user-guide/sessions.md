# Sessions

Conversation persistence lives at
`<workspace>/.symphony/sessions.sqlite3`. Resume with `session_id` in the
library API, or `symphony --resume` in the TUI (interactive picker). `/new`
starts a fresh persisted session.

```sh
uv run --package symphony-code symphony --resume
```

## What is stored

Messages, workspace path, and checkpoints as the run progresses. Compaction
keeps the system prompt, original task, and recent turns, and writes a summary
of dropped work. Tool-result stubs replace old bodies in the **model-facing**
copy once the prune budget is hit; persisted history stays linear until then.

<div align="center">
  <img src="../context-modal.png" alt="Context modal" height="240">
</div>

`/context` breaks down stored vs sent tokens by role.

## Library

`SqlitePersistence` implements the harness `Persistence` protocol. coding_agent
attaches it by default. A bare `CoreHarness` uses `NullPersistence`, so library
harness runs discard state unless you attach a store.
