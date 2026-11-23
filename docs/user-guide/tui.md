# Use the terminal interface

Symphony Code presents your task, model response, tool activity, and approval requests in one terminal conversation. Launch it from the repository workspace with `uv run --package symphony-code symphony`; use `--workspace PATH` to choose the project. See [Quickstart](../getting-started/quickstart.md) for the first run.

## The start screen

Before the first message, a card at the top shows whether the workspace has an `AGENTS.md`, how many skills and plugins loaded, and the active personality. Beside or below it are your five most recent conversations. Click one to reopen it in place. A tip under the card changes every few seconds. A `art = [...]` list in `.symphony/dashboard.toml` replaces the logo. The card drops recent rows and padding to fit short terminals.

## The conversation

Type a request in the composer and press Enter. While a run is active, the transcript shows model output and tool activity; approval or question prompts appear when interaction is needed. Review changes in your project—the transcript is a record of activity, not a substitute for checking the result.

## Controls

| Action | Control |
| --- | --- |
| Open the slash-command menu | Type `/` |
| Get workspace-path suggestions | Type `@` at the end of a path mention |
| Cancel an active run | `Esc` or `Ctrl+X` |
| Open subagent sessions | `Ctrl+G` |
| Open the agent dashboard | `Ctrl+B` |

You can ask for a plan as an ordinary conversation request, but there is no separate planning mode or plan-approval gate. Such a request does not restrict tools or replace normal tool approvals. Commands and shell side effects still require careful review. See the [security policy](../../SECURITY.md).

## Continue a conversation

Use `/new` to start a fresh session. Click a recent conversation on the start screen to reopen it, or launch with `--resume` to choose any saved session. A conversation open in another Symphony window cannot be reopened until that window moves on. Session storage and recovery behavior are documented in [Sessions](./sessions.md).

## Commands and configuration

Type `/` to discover commands, or consult the [slash-command reference](../reference/slash-commands.md). Change colors with `/theme` ([themes](./themes.md)). Change provider credentials and approval defaults in [Configuration](./configuration.md).
