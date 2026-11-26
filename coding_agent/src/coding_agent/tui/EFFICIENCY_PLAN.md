# TUI algorithmic efficiency

This tracks the rendering and event-loop work identified by comparing Symphony
with Grok Build (`xai-org/grok-build`) and fx (`vercel-labs/fx`). The goal is
the same algorithmic behavior, not a rewrite in another language.

## Done in this pass

- Thinking Markdown freezes stable top-level blocks and reparses only the open
  tail while a thought streams. A replacement, shrink, or style change discards
  the frozen prefix. Completed thoughts render once from the full source.
- Session event appends reuse a journal cache whose file size still matches.
  They no longer decode the whole transcript or republish unchanged artifacts
  on every event. A changed file size still forces a full reload. Appends,
  locks, and `fsync` stay synchronous and ordered.

## Done for live smoothness

- A stream paint, a tool-row update, and a thought update relayout only when
  the widget's fitted height changes. A same-height update dirties paint.
- One-line tool and Bash headers never relayout as their text grows.
- A card mounts inside one update batch. Its hidden collapsible title is not
  mounted, so label rewrites during compose do not schedule extra layouts.
- Folded tool groups keep a running tally. A status change no longer rescans
  the whole group. Colors, rates, and the tail-follow animation are unchanged.

## Still open

- Move remaining session operations off the UI event loop without reordering or
  weakening durability. Journal events, conversation saves, and checkpoint
  saves are offloaded and awaited; other operations may still block.
- Keep a bounded rendered tail for the live assistant message so layout work
  does not grow with the whole answer.
- Render or retain only the visible transcript region for long restored
  sessions, as fx does with its viewport and retained frame band.
- Revisit the 15 Hz stream-paint cap only after per-paint work is bounded.
