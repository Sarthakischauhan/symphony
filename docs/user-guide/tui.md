# Use the terminal interface

Symphony Code presents your task, model response, tool activity, and approval requests in one terminal conversation. Launch it from the repository workspace with `uv run --package symphony-code symphony`; use `--workspace PATH` to choose the project. See [Quickstart](../getting-started/quickstart.md) for the first run.

## The conversation

Type a request in the composer and press Enter. While a run is active, the transcript shows model output and tool activity; approval or question prompts appear when interaction is needed. Review changes in your project—the transcript is a record of activity, not a substitute for checking the result.

## Modes and controls

| Action | Control |
| --- | --- |
| Open the slash-command menu | Type `/` |
| Switch build/plan mode | `/mode` |
| Get workspace-path suggestions | Type `@` at the end of a path mention |
| Cancel an active run | `Esc` or `Ctrl+X` |
| Open subagent sessions | `Ctrl+G` |
| Open the agent dashboard | `Ctrl+B` |

Plan mode stages a plan before implementation; it is not a security sandbox. Commands and shell side effects still require careful review. See the [security policy](../../SECURITY.md).

## Continue a conversation

Use `/new` to start a fresh session. From the shell, launch with `--resume` to choose a saved session. Session storage and recovery behavior are documented in [Sessions](./sessions.md).

## Commands and configuration

Type `/` to discover commands, or consult the [slash-command reference](../reference/slash-commands.md). Change provider credentials and approval defaults in [Configuration](./configuration.md).
