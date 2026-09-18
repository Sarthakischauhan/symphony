# Langfuse telemetry

Symphony can send coding-agent traces to [Langfuse](https://langfuse.com) so you
can inspect the conversation actually sent to the model, tool calls, and
compaction.

The add-on is first-party (`coding_agent.langfuse.LangfuseAddon`). It is not a
plugin: plugin loading still requires `SYMPHONY_PLUGIN_AUTHORIZED_ROOTS`.

## What a trace contains

One Langfuse trace is one `CoreHarness.run` (one user task). Nested
observations:

| Observation | Type | Input / output |
| --- | --- | --- |
| `coding-agent-run` | span | User task in, final `output_text` out. Session id is the Symphony session. |
| `model-turn` | generation | The message list as it exists after `before_turn` (system prompt, memory, compacted history, tools already returned). Output is the assistant text plus any tool calls. |
| `<tool name>` | tool | Tool arguments in, bounded result out. |
| `compaction` | span | Token counts around a compact. |

Child agents inherit the add-on and emit their own traces, tagged with
`parent_id` / `agent_id`.

Every observation input and output that can carry user or tool text (the run
task, each turn's assistant text and tool calls, tool arguments, tool results,
and final `output_text`) goes through the same redaction path. Image parts are
replaced with `[image:filename]` so base64 never leaves the process.

## Enable it

From the TUI, run `/langfuse` and enter the public key, secret key, and base URL. The command saves them to `~/.symphony/.env` with restrictive file permissions and reloads the agent. You can also set the variables manually:

1. Create a Langfuse Cloud project or self-host Langfuse.
2. Put keys in the process environment, workspace `.env`, or `~/.symphony/.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # or US / self-hosted URL
```

3. Install the optional extra (not a default dependency):

```sh
uv sync --package symphony-code --extra langfuse
# or: pip install 'symphony-code[langfuse]'
```

Without keys, or without the package, the add-on mounts and does nothing.
Missing package logs a warning once at attach.

Disable it in spawn settings:

```json
{
  "langfuse": { "enabled": false }
}
```

`sample_rate` (0–1) drops whole runs. `max_payload_chars` bounds each serialized
observation payload (messages, tool arguments, tool results, and run input/output).

## Skill

The [Langfuse Agent Skill](https://github.com/langfuse/skills) is documentation
for querying traces, prompts, and datasets. Install it as a normal Symphony
skill if you want the agent to look those APIs up:

```sh
git clone https://github.com/langfuse/skills.git ~/.symphony/skills-src/langfuse-skills
ln -s ~/.symphony/skills-src/langfuse-skills/skills/langfuse ~/.symphony/skills/langfuse
```
