# TUI performance

Use this when a terminal screen feels blank, delayed, or stuttery. Measure the
actual path before changing it. A repaint optimization does not help when the
time is spent constructing widgets that are never shown.

## Measure first

1. Pick a real session or screen that reproduces the delay. Synthetic fixtures
   often hide the expensive content.
2. Time each stage separately: file read and parse, event hydration, widget
   construction, layout, and terminal paint.
3. Profile the slow stage with `cProfile` before editing. Record the session
   size and elapsed times beside the change so the next regression is obvious.
4. Run the targeted TUI test and `uv run ruff check .` after the change.

For the 15 MB session `9b357c18-4edd-4aba-aadd-b85c6d08c765`, parsing and event
hydration took about 0.55 seconds, while constructing the restored widgets took
another 1.17 seconds. Building 112 Bash widgets that were immediately folded
away accounted for most of that second stage. Replacing those discarded widgets
with snapshots reduced construction to 0.213 seconds.

## Build only what remains visible

- Do not construct a live widget for data that a summary will immediately fold
  away. Foreground Bash calls in completed runs are snapshots, not
  `BashToolWidget` instances.
- Keep interactive cards, such as background Bash and subagents, as real
  widgets because the user can open them.
- Parse Markdown when an assistant message is displayed, not merely because it
  exists in history. Rich Markdown construction was the next-largest cost in
  the profile.
- Cache listing fields beside a transcript. A session picker must not hydrate
  every message and image just to show a title and count.
- Keep membership sets while indexing a growing journal. Rebuilding a set from
  the accumulated list for every event is quadratic.

## Paint once

Textual's `App.batch_update()` suspends repaints until the batch ends. Mount a
group of restored widgets inside one batch instead of letting each insertion
schedule its own layout and paint.

Codex uses a stronger terminal-level version of this idea. It buffers the
complete replay, enters one synchronized terminal update, clears the old frame
inside that update, writes the full history, and reveals the completed frame
once. Symphony currently uses Textual's batching rather than raw synchronized
terminal output.

For a large resume, paint the latest turn first so the screen is usable, then
batch the older turns into the next update. Do not yield between individual
turns: each yield permits an intermediate repaint.

## Keep widget updates local

- Update text with `layout=False` when the widget's size cannot change.
- A streaming output tail should use a fixed-height window and replace its text
  in place. Do not append widgets for output chunks.
- Do not rebuild a parent, the top bar, or the whole transcript for a status or
  token update.
- Clip or measure a long string in one forward pass. Repeatedly shortening it
  and measuring the entire remainder is quadratic.
- Prefer snapshots and plain text for collapsed history. Create the expensive
  detail view only when the user opens that item.

## Resume checklist

- The newest turn appears before the full history has been mounted.
- Older history is inserted in one batched update.
- Folded tool calls do not construct widgets that are immediately discarded.
- Session listing uses size-keyed summary data, not a full transcript parse.
- A real multi-megabyte session is timed before and after the change.
- The stored transcript and model context remain complete; performance work
  changes display timing, not history retention.
