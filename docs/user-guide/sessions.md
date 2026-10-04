# Sessions

Every session owns a directory at `~/.symphony/sessions/<session_id>/`.
Resume with `session_id` in the library API, or `symphony --resume` in the
TUI (interactive picker). `/new` starts a fresh persisted session.

```sh
uv run --package symphony-code symphony --resume
```

## What is stored

```text
<session_id>/
  metadata.json            # storage format and session identity
  transcript.jsonl         # append-only messages, lifecycle events, checkpoints
  checkpoint.json          # latest slim checkpoint; no duplicate transcript
  state.json               # stdio mode/effort, when configured
  images/                  # content-addressed attachment and tool-result images
  compactions/             # individually inspectable summary snapshots
  memory/
    MEMORY.md              # sanitized snapshot of shared workspace memory
    USER.md                # sanitized snapshot of global preferences
    operations.jsonl       # successful and rejected memory operations
  learning/
    captures.jsonl         # durable capture job and observation provenance
    context.jsonl          # queried/injected topics and extraction evidence
  run.json                 # detached-run pid, arguments, and workspace
  run.log                  # detached-run stdout/stderr
```

Files are created as their corresponding features are used. Each child agent
has its own directory, linked by the parent's persisted spawn events. The
resume picker omits child sessions and sessions owned by live processes.

The transcript is the source of truth. Messages and completed lifecycle events
append as the run progresses. Compaction preserves the entire historical
transcript and records a summary boundary; resume reconstructs the model's
context from the latest boundary plus subsequent messages. The visible
transcript retains messages from before compaction. Checkpoint and compaction
files are inspection artifacts, not independent copies of model context.
Streaming token deltas are not stored.

Embedded images are archived once by content hash rather than repeatedly
storing base64 in the transcript. Loading hydrates them into provider-compatible
content and the TUI's existing image previews. Remote image URLs remain URL
references: storage does not fetch arbitrary URLs. Keep the whole session
directory together when copying or backing it up.

Existing flat `<session_id>.jsonl` files remain readable and are migrated into
the session directory when accessed. Old workspace `.sessions` files are still
collected into the global session directory. No manual conversion is required.

## Inspecting history and memory

- `/session` opens a read-only archive inspector with checkpoint/state details,
  every compaction summary, session memory snapshots and operation history,
  learning/context records, child links, lifecycle events, and image previews.
  The stdio transport exposes the same command as a text report.
- `/learning` shows curated workspace/global topics and pending capture/inbox counts.
- `/context` breaks down only the active model context by role.

Durable knowledge lives in workspace `.symphony/memory-v2/` topic files, with
cross-project preferences under `~/.symphony/memory-v2/global/`. Every completed
turn queues bounded sanitized capture evidence durably; a background worker
extracts candidate observations, then consolidation groups and deduplicates
facts into curated topics. Interrupted jobs survive shutdown and resume later.
Only curated topics are retrieved, via a local full-text index. Historical
session transcripts and snapshots are inspection data, not retrieval sources.
See [Memory and learning](learning.md) for scope, ingestion, and retrieval rules.

## Continuing interrupted runs

`symphony --resume --continue` skips the picker. If the most recent session's
last checkpoint still says `running` (the process died mid-run), it starts a new
unattended run in that session with a note describing the interruption,
background jobs, and original goal. Background jobs run in their own process
group and can outlive a killed `symphony`; `--continue` kills any recorded job
group (`background_jobs` holds `{job_id: pid}`) that is still alive. Checkpoints
carry `goal`, `todo`, and `background_jobs` metadata. The goal is also the pinned
first user message, so compaction keeps it.

## Library

`JsonlPersistence` implements the harness `Persistence` protocol and remains
the public backend name for compatibility. coding_agent attaches it by default.
`session_dir(session_id)` locates the bundle; `load_compactions(session_id=...)`
returns the complete compaction history. A bare `CoreHarness` uses
`NullPersistence`, so library harness runs discard state unless you attach a
store.
