# Coding agent host protocols

`stdio.py` is the versioned JSONL boundary for desktop and other external
hosts. The coding agent owns execution and persisted checkpoints. A host owns
its composer queue and submits a single prompt per active turn.

Protocol version 1 advertises `runs`, `resume`, `interrupt`, `input`, `models`,
`images`, and `subagents` in its `ready` frame. A host sends `run`, `answer`, or `interrupt`
commands and reads `event`, `input_requested`, `error`, and `done` frames.
Unknown control-plane events can be ignored without losing the terminal
`done` frame. A later version must change the version number when it changes
required frame semantics.

Subagents use the ordinary `event` envelope: the parent emits
`agent_spawned` with `child_id` and `tool_call_id`; child events carry that
`child_id` as `agent_id`; the parent emits `agent_completed` or `agent_failed`
with `child_id` when it settles. Hosts can route child traffic into a nested
view using the spawning tool call ID.
