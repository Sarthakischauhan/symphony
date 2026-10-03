# Learning

Learning uses a small, curated memory rather than injecting the legacy lesson
archive. The `memory` tool writes sanitized entries to
`<workspace>/.symphony/memory/MEMORY.md` or `USER.md`; both files are shown by
`/learning`; relevant entries are queried and injected as bounded, untrusted
reference data into the system prompt.
Duplicate additions are no-ops and bounded files report their current entries
when the limit is exceeded. Procedures belong in skills, not memory. The legacy
`<workspace>/.symphony/learning/lessons.jsonl` remains a compatibility archive, displayed by `/learning` but not used for
retrieval.

Learning is enabled by default. Reflection may propose durable memory updates
and a two-line recap, but plan mode skips reflection. The harness sees learning
only as `LearningAddon` hooks (`notify_addons`); there is no parallel learning
control plane. Children do not inherit the add-on.

## Disable it

- `"learning": {"enabled": false}` in the spawn settings file.
- `enable_learning=False` on the agent.
- `symphony --no-learning` on the TUI (this also omits the `memory` tool).

Children do not inherit post-run reflection (`LearningAddon.fork_for_child`
returns `None`). Their session-local memory add-on binds a separate memory tool
when one is available and records queried/injected shared memory under the
child session, without rebinding the parent tool.

## Shutdown

Call `await agent.shutdown_learning()` (or `wait_for_learning()`) when an
application needs to cancel or drain pending reflection before exit. The TUI
does this automatically. `/learning` opens `MEMORY.md`, `USER.md`, and reusable
workspace lesson records.

## Session provenance

Sessions archive sanitized memory snapshots and successful/rejected memory
operations under `memory/`, plus queried/injected context, reflection input, and
post-run review lessons under `learning/`. `/session` presents these records.
Historical session archives are inspection data, never a second retrieval
source. Durable memory remains shared by workspace; session review records are
not automatically promoted to durable memory. See [Sessions](sessions.md).
