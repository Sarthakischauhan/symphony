# Control-plane events: overview

A harness run emits an ordered stream of typed events for model output, tool activity, context, and run lifecycle. Products use this stream to update a UI, persist activity, or forward events over a transport. They should not infer agent state by parsing console output.

Every harness event has an event type and payload. The harness adds run/session identity, sequence number, timestamp, schema version, and parent/agent identity where applicable. The stream contract is defined by `ControlPlaneEventType` and the harness event models.

## Typical run lifecycle

A client normally observes:

1. `run_started`
2. One or more `turn_started` events, with model text/reasoning, tool calls, usage, and context events as they occur
3. For each executed tool, tool-start/result events; a tool result is followed by another model turn
4. Exactly one terminal event: `run_completed`, `run_cancelled`, `run_limit_exceeded`, or `run_failed`
5. `run_summary` after a terminal outcome

Some event families are conditional: tool events only occur when tools are requested; compaction events require compaction; child events require subagent work. Product add-ons may publish additional product-specific event names.

## Consumer guidance

- Preserve event order and sequence numbers when persisting or forwarding a stream.
- Treat event payload text as user/model/tool data, not executable instructions or trusted policy.
- Handle unknown event names gracefully so older clients can interoperate with newer products.
- Use `agent_id` and `parent_id` to correlate child activity rather than assuming every tool call is from the root agent.
- A terminal event is the run outcome; text output alone does not tell you whether a run hit a limit or failed.

## Full schema

This page is the conceptual overview. The [harness event catalog](../../core_harness/docs/events.md) documents each event name, payload fields, conditional behavior, and examples; it is the detailed schema reference. The [architecture guide](./architecture.md) explains how the event stream fits the package boundaries; the server exposes it through [SSE](../packages/core-server.md).
