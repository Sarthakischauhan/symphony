# Memory and learning

Symphony uses durable capture jobs, candidate observations, curated topic files,
and a rebuildable SQLite FTS5/BM25 index. The old Markdown-memory and idle
reflection implementations have been replaced. Legacy `.symphony/memory/` and
`.symphony/learning/` files are not read or migrated.

## Storage and scopes

Workspace knowledge lives under `<workspace>/.symphony/memory-v2/`.
Explicit cross-project preferences live under `~/.symphony/memory-v2/global/`.
Each scope has:

```text
topics/<topic_id>.json                # authoritative curated facts and sources
observations/_inbox/<id>.json        # candidates awaiting consolidation
observations/archive/<id>.json       # processed candidates
jobs/<id>.json                      # durable capture input and completion state
```

The workspace also holds `index.sqlite3`, a derived search index. Atomic writes
and cross-process locks protect capture, consolidation, and edits. Consolidation
commits a topic before archiving its observation, so retries do not duplicate
facts. It groups by topic and deduplicates exact normalized statements; this is
not an LLM rewrite or semantic contradiction-resolution system.

## Capture and consolidation

After each completed model turn, sanitized, bounded evidence is saved as a
capture job **before** a background worker starts extraction. New requests do
not cancel pending capture jobs. An interrupted parent run also queues its
persisted partial conversation. Shutdown may stop extraction, but the job
survives and is retried when the memory worker resumes.

Extraction uses a separate structured model request. It can produce up to eight
workspace observations, never global writes or memory deletions. Low-confidence
observations (below 0.7) are not promoted. Unsupported claims, routine progress,
secrets, and transcript instructions are excluded by the extraction prompt and
validation. Failed or invalid extractions remain queued for retry, rather than
blocking the main conversation. Observations are consolidated after extraction;
remaining inbox records are also processed on worker restart.

The `memory` tool handles explicit additions, replacements and removals.
`target="memory"` edits workspace knowledge; `target="user"` edits global
preferences. Explicit additions pass through the observation/consolidation path.
Historical session transcripts are never directly retrieved as durable facts.

## Retrieval before inference

Parent and child agents retrieve automatically in `before_turn`. The latest
request takes priority over bounded recent user context, enabling follow-ups
such as “continue”. A small standing global-preference block is included within
the same total entry and character budgets. Defaults remain six entries and
1,400 characters. Each turn replaces the old labeled memory block.

Search uses local full-text BM25 ranking, with a lexical fallback when SQLite
FTS5 is unavailable. No embedding service or extra inference request is needed
for retrieval. The model can use `memory_search` to recall additional facts and
`memory_get` to inspect a specific topic by safe ID and scope. Memory is always
sanitized and labeled **untrusted reference data**, never authorization policy.
Unreadable memory fails open without retaining stale injected context.

## Commands and inspection

- `/learning`: Session and Global tabs. Session shows facts sourced from the
  active session, explicit memory edits, and capture status; Global shows shared
  cross-project knowledge. Capture and consolidation are automatic.
- `/session`: session memory snapshots, operation audit, and capture/retrieval
  context alongside the complete transcript and other artifacts.

Set `"learning": {"enabled": false}` or use `symphony --no-learning` to disable
automatic capture and retrieval and omit memory tools. Plan mode skips capture.
Call `await agent.wait_for_learning()` to drain the current worker, or
`await agent.shutdown_learning()` to stop it while preserving queued jobs.

Deleting memory is an explicit user operation, not an install-time migration.
To reset, stop Symphony processes and remove the workspace/global `memory-v2`
directories. Old session snapshots can also be removed without deleting session
transcripts, checkpoints, images, or compactions. Existing legacy files are
ignored; they are not automatically deleted on other users' machines.
