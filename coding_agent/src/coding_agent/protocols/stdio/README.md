# Coding agent host protocols

`stdio.py` is the versioned JSONL boundary for desktop and other external
hosts. The coding agent owns execution and persisted checkpoints. A host owns
its composer queue and submits a single prompt per active turn.

Protocol version 2 advertises `runs`, `resume`, `interrupt`, `input`, `steer`,
`models`, `images`, `subagents`, and `commands` in its `ready` frame. A host
sends `run`, `answer`, `interrupt`, or `steer` commands, or `model/list` with a
`request_id`, and reads `event`, `input_requested`, `error`, `done`, and
`models` frames. `answer`, `interrupt`, and `steer` are passed to
`CoreHarness.submit` as `Answer`, `Interrupt`, and `UserInput` operations.
`{"type":"steer","prompt":"..."}` adds a user message to the active run before
its next model call and is an error when no run is active.

A question arrives as the ordinary `question_asked` event, the same as in
every other host, followed by the protocol 2 `input_requested` frame with the
same `request_id`. Reply to either with one `answer` command.
Unknown control-plane events can be ignored without losing the terminal
`done` frame. A later version must change the version number when it changes
required frame semantics.

After `ready`, send `{"type":"model/list","request_id":"catalog-1"}` on stdin.
Symphony responds with a `models` frame carrying the same `request_id`. Each
row has a qualified
`id` (`provider:model`), display `label`, `provider`, `description`,
`context_limit` (tokens, or null), and `reasoning_levels`. The default ID is
also returned as `default`; hosts should keep the qualified ID when selecting
a model. The provider is the API route, so gateway models identify the gateway
even when its upstream model has another vendor.

Subagents use the ordinary `event` envelope: the parent emits
`agent_spawned` with `child_id` and `tool_call_id`; child events carry that
`child_id` as `agent_id`; the parent emits `agent_completed` or `agent_failed`
with `child_id` when it settles. Hosts can route child traffic into a nested
view using the spawning tool call ID.
