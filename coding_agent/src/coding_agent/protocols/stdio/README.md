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

## Protocol 3: widget fields

`hello` reports `"protocol": 3` and the `widget_fields` capability. Every
protocol 2 key is unchanged; hosts that ignore unknown keys keep working.
The stdio server and the TUI add these fields through one shared
`coding_agent.protocols.fields.EventFields`. `parent_call_id` is the
`tool_call_id` of the `spawn_agent` call that started the emitting subagent,
and `null` for top-level events.

| Event | Added fields |
| --- | --- |
| `tool_execution_started` | `call_id`, `parent_call_id` (`started_at` was already present) |
| `tool_execution_output` | `call_id`, `stream` (`"stdout"` or `"stderr"`), `parent_call_id` |
| `tool_execution_completed` | `call_id`, `exit_code`, `summary`, `parent_call_id` (`status` and `duration_ms` were already present) |
| `question_asked` (approval) | `target`, `detail`, `bytes` (`tool_call_id`, `choices`, `default` were already present) |
| `input_requested` (approval) | top-level `target`, `detail`, `bytes` (also kept in `metadata`) |
| `agent_spawned` | `parent_call_id` (same value as `tool_call_id`) |
| `subagent_step` (new, derived) | `agent_id`, `parent_id`, `parent_call_id`, `turn`, `started_at`; follows each subagent `turn_started` |

- `exit_code` is the bash process's exit status; it is `null` for other tools,
  background jobs, and timeouts. A non-zero exit is `status: "error"` and the
  result starts with `exit=N`, but consumers should read `exit_code`.
- `summary` is `{lines, matches, added, removed}`, each an integer or
  `null`: `lines` for bash and read_file, `matches` for search, `lines` and
  `added` for write_file, `added` and `removed` for patch. Failed non-bash
  calls report all `null`.
- Answer an approval with the existing `input` frame using one of `choices`.
- `bytes` is the UTF-8 size of a write_file `content` or patch `new_str`, else `null`.
- Derived fields are added on delivery and are not persisted; resumed
  sessions replay protocol 2 payloads, and clients should fall back to deriving
  them.
