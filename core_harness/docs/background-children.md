# Background children

`SubagentAddon(background=True)` makes the model-facing `spawn_agent` tool
return a JSON acknowledgement with `child_id`, `parent_id`, `session_id`,
`status`, and `output_text`. The bare add-on retains its foreground default;
coding_agent enables background execution. The model can override it per call.

The harness owns each background task, its result, and shutdown. Children use
independent harness/session instances; the maximum number of active background
children is `max_parallel_tool_calls`. Waiting and result delivery are runtime
operations, not additional model tools. Hosts must await
`harness.shutdown_children()` on shutdown.

Completed child results enter an inbox drained before the parent's next model
turn. If the parent finishes independent work first, the runtime emits
`waiting_for_children`, awaits a child completion, and schedules the next model
turn with that result. It emits the final parent completion only after all
children have finished and their results have been incorporated. Parent
cancellation or a run limit stops its background children.

Every child event carries its own agent, parent, session, run, and sequence
identity. Parent lifecycle events also include the originating `tool_call_id`
and `child_session_id`, so views do not need to match prompts or labels.
Lifecycle events use the active parent event sequencer.

Conversation/checkpoint persistence remains pluggable. A persistence backend
may additionally implement `append_event(event_type=..., payload=...)` to
journal identified updates before they reach the UI. coding_agent's SQLite
backend batches streaming deltas, flushes lifecycle boundaries, indexes child
metadata, and supports transcript reload by child session ID. Child persistence
is selected through `ChildConfig`; coding_agent supplies the same backend in
separate child persistence and compaction add-ons.

These are application-owned asynchronous tasks, not detached OS processes.
Persisted history does not imply that a task keeps executing after host exit.
