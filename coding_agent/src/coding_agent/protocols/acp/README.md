# Agent Client Protocol host

`symphony acp [--model PROVIDER:MODEL] [--unattended]` speaks the
[Agent Client Protocol](https://agentclientprotocol.com) (version 1) as
JSON-RPC 2.0 over stdio, one message per line. Editors and other ACP clients
start it as a child process. Standard output carries protocol messages only;
diagnostics go to standard error.

The host is a translator. It owns no agent logic: the same event stream and
the same `CoreHarness.submit` operations drive the TUI and the JSONL host.

## What is implemented

| ACP | Symphony |
| --- | --- |
| `initialize` | Returns protocol version 1, `agentInfo`, and capabilities. |
| `session/new` (`cwd`) | Builds a coding agent for that workspace. The reply's `sessionId` is the Symphony session id. One process can hold several sessions. |
| `session/prompt` | Runs one turn on the prompt's text. The reply carries `stopReason`: `end_turn`, `cancelled`, `max_turn_requests`, or `max_tokens`. |
| `session/cancel` | `Interrupt("user_cancel")`. |
| `session/update` | Sent for `text_delta` (`agent_message_chunk`), `reasoning_delta` (`agent_thought_chunk`), tool events (`tool_call`, `tool_call_update`), `context` (`usage_update`), and injected user input (`user_message_chunk`). |
| `session/request_permission` | Sent for a `question_asked` event that has choices, such as an approval. The selected option is returned to the run as an `Answer`. |
| `_symphony/steer` (`sessionId`, `prompt`) | Extension. `UserInput`: adds a user message before the run's next model call. Replies `{"accepted": bool}`. Advertised under `agentCapabilities._meta.symphony.steer`. |

## Limits

- `session/load` is not implemented (`loadSession` is `false`). Start a new
  session instead.
- Prompts are flattened to text. `text`, `resource_link`, and text
  `resource` blocks are read; images and audio are not.
- `mcpServers` in `session/new` is ignored.
- Only the root agent is narrated. A subagent appears as the parent's
  `spawn_agent` tool call.
- A question without choices (a free-text `ask_user`) cannot be expressed as
  a permission request, so it takes its default answer.
- A cancelled or malformed permission outcome denies an approval.
- Session modes, config options, plans, and slash commands are not exposed.
