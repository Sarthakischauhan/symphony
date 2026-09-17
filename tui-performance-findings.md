# TUI performance findings

Investigation: 2026-09-10 · source revision `7cea045` · installed Textual `8.2.8`.

This is a diagnostic report, not an implementation or a claim that the proposed architecture already exists. No application code was changed. Measurements use generated conversations, temporary storage, and a headless Textual app; no provider requests or personal session contents were used.

## Assessment

There are concrete reasons for the lag beyond terminal rendering. The UI shares an event loop with synchronous session storage, filesystem tools, and child-agent bookkeeping. Several operations become more expensive as conversations grow. Existing paint throttling reduces some rendering work but cannot make a blocked event loop responsive.

The first priorities are incremental persistence, moving blocking work off the UI loop, fixing child-event repainting, and loading only a bounded window of history. A framework rewrite is not justified by the evidence collected so far.

## Measured evidence

Local synthetic persistence benchmark: alternating user/assistant messages with approximately 2 KiB of text each, written using the actual `JsonlPersistence.save_conversation`. Appends are medians of ten distinct lifecycle events. The file sizes include the writer's duplicate message representation. These are warm local runs, not cold-disk or production latency measurements.

| Messages | Session size | Append one event | Load transcript + context | Picker, one session |
| --- | ---: | ---: | ---: | ---: |
| 100 | 0.45 MiB | 2.17 ms | 5.70 ms | 3.67 ms |
| 1,000 | 4.44 MiB | 16.78 ms | 40.49 ms | 34.71 ms |
| 5,000 | 22.21 MiB | 87.28 ms | 223.60 ms | 171.58 ms |

Instrumentation confirmed **ten complete file reads for ten event appends**. A callback queued with `call_soon` before `await load_transcript(...)` had still not run when the load returned: the async load did not yield to the event loop.

Separate UI benchmark: the real `_history_widgets`, `mount_transcript_batch`, and `finalize_transcript_history` methods inside a minimal Textual app at 100 × 35 cells. Each message contains approximately 512 bytes of simple text. This excludes agent construction and file loading.

| Messages | Construct widgets | Synchronous mount/freeze call | Mount through `pilot.pause()` | Mounted message widgets |
| --- | ---: | ---: | ---: | ---: |
| 100 | 48 ms | 43 ms | 321 ms | 100 |
| 500 | 229 ms | 310 ms | 1,522 ms | 500 |
| 1,000 | 479 ms | 1,048 ms | 3,403 ms | 1,000 |

The last timing includes Textual processing and Pilot's settling overhead; it is not a measured terminal frame time. At 1,000 messages, construction plus the synchronous mount/freeze calls alone took about **1.53 seconds**. An earlier run showed the same trend, at about 1.38 seconds. Rich Markdown, images, and tool-heavy transcripts require separate workloads.

The diagnostic script remains at `/private/tmp/symphony_tui_findings_bench.py` for this workspace session. Re-run with `.venv/bin/python /private/tmp/symphony_tui_findings_bench.py`. It creates and cleans up its own temporary session directories. It is an exploratory benchmark, not a CI performance test.

## Findings

### 1. Persistence blocks input and becomes slower with session size — highest priority

[`JsonlPersistence`](coding_agent/src/coding_agent/persistence/jsonl.py) declares async methods but performs synchronous file I/O, JSON decoding, model validation, and locking inside them. `append_event` rereads the whole file and rebuilds known event keys before appending. `save_conversation` serializes the incoming context, rereads the journal, reconstructs stored context, and compares them. `save_checkpoint` also rereads the file.

[`CoreHarness.emit`](core_harness/src/core_harness/harness.py) awaits persistence **before** forwarding the event to the UI. `_persist_state` saves both conversation and checkpoint. Thus storage blocks both runtime progress and UI responsiveness. Token deltas are already excluded from disk persistence, but lifecycle and tool events still pay this cost.

If journal size grows roughly with event count, rereading it for every append produces approximately quadratic cumulative read/parse work. Moving that same algorithm to a thread can improve responsiveness but leaves its growing total cost intact.

Recommended direction: one serialized storage owner, incremental append metadata, and indexed context/transcript projections. A small transactionally maintained SQLite store is an option; retaining JSONL with a rebuildable side index is also viable. Benchmark both before choosing. Preserve event ordering, compaction semantics, deduplication, crash recovery, and explicit flush/error handling. Do not silently turn durable writes into fire-and-forget tasks.

### 2. The resume picker scans every session and misses the current message format

[`list_sessions`](coding_agent/src/coding_agent/persistence/jsonl.py) decodes every JSON line of every session, despite its comment suggesting a cheap metadata scan. It also discovers child-session IDs by scanning spawn records.

There is a specific mismatch: `_message_entry` writes `type="message"`, whereas `list_sessions` counts only `system`, `user`, `assistant`, and `tool_result` types. Current-format sessions therefore produce zero message count and an empty title. [`load_session_options`](coding_agent/src/coding_agent/tui/screens/resume.py) then falls back to loading their full transcripts again. The benchmark reproduced zero summary count followed by the correct fallback count at all three sizes.

[`__main__.py`](coding_agent/src/coding_agent/tui/__main__.py) finishes loading options before starting `ResumeApp`, so this work appears as a startup wait with no picker feedback. Session storage is global under `~/.symphony/sessions`, making accumulated sessions relevant even when the current workspace is small.

Recommended direction: fix message-format recognition first; maintain a rebuildable session catalog containing title, counts, last activity, and parent linkage. Open the picker immediately and page catalog results. Fixing the format mismatch alone still leaves the initial all-files scan.

### 3. Conversation history is fully materialized; tool condensation is not virtualization

Current resume path:

1. The CLI scans sessions and runs the picker.
2. `CodingAgentApp.on_mount` builds the agent synchronously.
3. An async Textual worker loads the complete transcript, then separately loads active model context for token estimation.
4. `_history_widgets` constructs every user/assistant widget and summarized tool row.
5. `mount_transcript_batch` loops over the whole list and calls `mount` per widget; finalization scans and freezes message renders.
6. `restore_subagents` loads parent child metadata, then eagerly loads each child's persisted events.
7. A later model run loads active context again through `_initial_messages` when no conversation is supplied.

Sources: [`app.py`](coding_agent/src/coding_agent/tui/app.py), [`history.py`](coding_agent/src/coding_agent/tui/screens/history.py), [`surface.py`](coding_agent/src/coding_agent/tui/transcript/surface.py), [`subagent.py`](coding_agent/src/coding_agent/tui/runtime/subagent.py), [`harness.py`](core_harness/src/core_harness/harness.py).

The distinction between complete visual transcript and compacted model context is correct and should survive optimization. Model-context compaction does not reduce the complete transcript loaded for the UI.

There is no bounded conversation viewport: old message widgets remain mounted. `_compact_transcript` scans all recorded turns on various tool/turn transitions. Completed tool cards are condensed and their snapshots clipped, which helps, but does not bound conversation widget count or repeated history traversal.

Recommended direction: transcript records independent of widgets, indexed page reads, latest-page-first restore, and a bounded mounted window with overscan. Preserve scroll anchors when prepending history and resizing. Fetch older tool details and child histories on demand. Reconcile only dirty turns. Selection, copying, search, and expanding old content need explicit behavior when records are not mounted.

### 4. Child agents bypass paint throttling and retain full live event histories

[`TextualEventSink.emit`](coding_agent/src/coding_agent/tui/runtime/sink.py) posts one Textual message per event. Parent text/reasoning/tool paints are coalesced to 15 Hz, but event ingestion itself is not coalesced.

In [`subagent.py`](coding_agent/src/coding_agent/tui/runtime/subagent.py):

- `SubagentRecord.ingest` retains each live event and its payload, plus deduplication keys and derived tool/output state.
- Tool argument deltas concatenate the growing argument string and attempt `json.loads` on every delta; `_tool` linearly searches the child's tool list.
- `_on_child_event` refreshes bound parent cards on each event, even when the child's displayed label/status has not changed.
- For the open child screen, `refresh_record` updates heading/footer and invokes `TopBar.set_context` on each event. The topbar reads Git metadata before deciding whether a repaint is needed.
- `refresh_record` unconditionally calls `flush_stream_paints`, defeating the child screen's scheduled 15 Hz batching.
- Reopening a child creates a new screen and replays the retained event history from its start.

Recommended direction: a shared per-agent reducer, dictionary tool lookup, chunk buffers, bounded pending visual updates, and one scheduled paint for dirty visible content. Flush immediately at semantic boundaries such as completion and questions, not every delta. Retain durable/replayable state without keeping all raw live deltas indefinitely. Hidden children should update compact state without repainting unchanged cards.

### 5. Filesystem work also runs on the UI loop

[`WorkspaceTool.execute`](coding_agent/src/coding_agent/tools/base.py) calls synchronous `run` methods directly. The [`search tool`](coding_agent/src/coding_agent/tools/search.py) materializes a recursive traversal before applying file filters. Skipped directories are filtered after traversal; the binary sniff uses `read_bytes()[:limit]`, reading the whole file before slicing, and text files are then read again.

[`on_text_area_changed`](coding_agent/src/coding_agent/tui/composer/surface.py) calls file completion directly. A cold or invalidated [`WorkspaceFileIndex`](coding_agent/src/coding_agent/tui/screens/file_selector.py) walks and stats files in that input handler. Completed bash/write/patch tools invalidate this cache. The diff screen also invokes synchronous `subprocess.run` while composing its contents.

Recommended direction: offload appropriate blocking reads/searches, prune directories before descending, read only the binary sample, and stop traversal when enough results exist where ordering permits. Prewarm the file index in the background; debounce ranking, retain the last usable index during refresh, and discard stale query results. Run diff collection asynchronously and bound its display work.

Do not mechanically thread every tool: cancellation and mutation semantics must be preserved, and cancelling an awaiting coroutine does not necessarily stop the underlying thread.

### 6. Startup performs synchronous construction and discovery

`CodingAgentApp.on_mount` invokes `build_agent`, which resolves settings and constructs the agent, including plugin and skill discovery. `core_ai.__init__` also eagerly imports provider modules. These are additional startup candidates, but their contribution was not profiled here. Instrument import time and construction phases before optimizing them. Render a usable initial screen while suitable discovery work runs outside the UI loop.

## What “multiple processes” means here

| Work | Current execution model | Consequence |
| --- | --- | --- |
| Main agent turn | Async Textual worker, exclusive run group | Shares the UI event loop; async syntax provides no isolation from synchronous work |
| Background child agents | `asyncio.create_task` | Concurrent tasks in the same process/loop; blocking work in one can stall siblings and UI |
| Parallel tools | `asyncio.gather` in bounded chunks | Default harness limit is three; synchronous tool bodies still execute on the loop |
| Shell commands | Actual OS subprocesses with async pipe reads | Output is drained in 4 KiB chunks and retained with a byte cap |
| Separate Symphony launches | Independent application processes | The persistence lock is per store instance, not a cross-process session lock |

Sources: [`turn.py`](coding_agent/src/coding_agent/tui/runtime/turn.py), [`background.py`](core_harness/src/core_harness/addons/subagent/background.py), [`loop.py`](core_harness/src/core_harness/loop.py), [`config.py`](core_harness/src/core_harness/config.py), [`bash.py`](coding_agent/src/coding_agent/tools/bash.py).

The background-child limit checks active children against the parent's parallel-tool setting; it is not a machine-wide CPU/process scheduler. Bash already uses asynchronous subprocess execution, bounded output, timeout handling, and cancellation cleanup with process-group signals. That is a useful foundation; it is not the first component to rewrite.

For separate launches, distinct sessions have distinct files, but concurrent writes to the same session have no transaction or ownership mechanism spanning processes. This is a concurrency design gap, not a reproduced corruption claim. Any cache/index design must handle external file changes and define session ownership.

## Proposed implementation sequence

1. **Establish budgets and traces.** Measure event-loop delay, input-to-paint latency, event queue age, store read/append time, mounted widget count, history first-paint time, and memory. Cover fresh/resumed sessions and zero/one/three children, including an open child screen.
2. **Remove proven repeat work.** Fix picker decoding, child forced flushes, unchanged chrome refreshes, full-journal reads per append, and all-history reconciliation. Preserve lifecycle ordering and approval responsiveness.
3. **Isolate blocking work.** Introduce a serialized storage worker and cancellable background read/search/index operations with immutable results delivered to the UI. Add generation checks so late history/search results cannot overwrite newer state.
4. **Bound history cost.** Introduce indexed transcript records and a windowed renderer; restore recent content first and hydrate older/child content on demand. Keep model context and visual history as separate projections.
5. **Evaluate stronger runtime isolation.** If traces still show contention, run the agent runtime in a dedicated thread or process behind the existing event boundary. A process offers stronger CPU isolation but requires explicit protocol, cancellation, restart, and interaction routing. Do not spawn one process per child by default.

Suggested initial targets, to validate on a specified reference machine: input-to-paint p95 below 50 ms during streaming; no routine main-loop task over 16 ms; recent-history first paint below 250 ms on warm indexed storage; event-append cost approximately independent of accumulated transcript size; bounded mounted history widgets. These are proposed acceptance criteria, not achieved results.

Correctness checks should cover compacted and legacy sessions, resume during interrupted child runs, terminal resizing and scroll anchoring, completion after buffered deltas, disk errors, shutdown flushing, and same-session writer ownership. Use fake providers and generated fixtures.

Approval prompts, bash cancellation, and spawning are part of this repository's trust model. Any implementation changing their behavior needs discussion before edits and a `SECURITY.md` update if guarantees change. The report does not propose relaxing those guarantees or moving product-specific filesystem/UI behavior into `core_harness`.

## Existing improvements to preserve and investigation limits

The code already has parent paint batching, plain-text streaming followed by final Markdown, completed render caching, coalesced tail scrolling, compact tool snapshots, a cached file index, paused inactive status animations, and bounded subprocess output. Their presence explains why simply adding another throttle is unlikely to resolve the core issue.

The Textual skill informed the event-loop/worker review. Official [Textual worker documentation](https://textual.textualize.io/guide/workers/) confirms that blocking APIs require thread workers or another appropriate execution boundary, and widget updates must return to the UI thread. Async workers alone do not move synchronous work off that thread.

This investigation demonstrates scaling costs and identifies causal blocking paths. It does not attribute every observed user pause: actual terminal rendering, provider latency, production session shapes, plugin startup, RSS growth, and sustained multi-agent load still need end-to-end traces. No framework replacement, storage migration, or runtime behavior change was performed.
