# Learning

Learning uses a small, curated memory rather than injecting the legacy lesson
archive. The `memory` tool writes sanitized entries to
`<workspace>/.symphony/memory/MEMORY.md` or `USER.md`; both files are shown by
`/learning` and injected as untrusted reference data into the system prompt.
Duplicate additions are no-ops and bounded files report their current entries
when the limit is exceeded. Procedures belong in skills, not memory. The legacy
`<workspace>/.symphony/learning/lessons.jsonl` remains an unused migration archive.

Learning is enabled by default. Reflection may propose durable memory updates
and a two-line recap, but plan mode skips reflection.

## Disable it

- `"learning": {"enabled": false}` in the spawn settings file.
- `enable_learning=False` on the agent.
- `symphony --no-learning` on the TUI (this also omits the `memory` tool).

Children do not inherit the learning add-on or memory tool.

## Shutdown

Call `await agent.shutdown_learning()` (or `wait_for_learning()`) when an
application needs to cancel or drain pending reflection before exit. The TUI
does this automatically. `/learning` opens `MEMORY.md` and `USER.md`.
