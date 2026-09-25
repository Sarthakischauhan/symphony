# Sessions

Conversation persistence lives at
`~/.symphony/sessions/<session_id>.jsonl`. Resume with `session_id` in
the library API, or `symphony --resume` in the TUI (interactive picker). `/new`
starts a fresh persisted session.

```sh
uv run --package symphony-code symphony --resume
```

`symphony --resume --continue` skips the picker. If the most recent session's
last checkpoint still says `running` (the process died mid-run), it starts a new
unattended run in that session with one note: when it was interrupted, which
background jobs were lost, and the original goal. Checkpoints carry `goal` (the
first prompt), `todo` (the active plan file, if any), and `background_jobs`
metadata for this. The goal is also the pinned first user message, so
compaction keeps it.

## What is stored

One JSONL file per session (including child agents). Messages append as the run
progresses; compaction currently rewrites the message entries in that file.
Checkpoints are slim status records, not a second copy of the transcript.
Token deltas are not stored. During a run, the model receives every stored
message. Summary compaction retains the configured number of recent tool
results in full.

<div align="center">
  <img src="../context-modal.png" alt="Context modal" height="240">
</div>

`/context` breaks down the active context by role.

## Library

`JsonlPersistence` implements the harness `Persistence` protocol. coding_agent
attaches it by default. A bare `CoreHarness` uses `NullPersistence`, so library
harness runs discard state unless you attach a store.
