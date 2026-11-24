# Use the terminal interface

Symphony Code presents your task, model response, tool activity, and approval requests in one terminal conversation. Launch it from the repository workspace with `uv run --package symphony-code symphony`; use `--workspace PATH` to choose the project. See [Quickstart](../getting-started/quickstart.md) for the first run.

## The start screen

Before the first message, a card at the top shows whether the workspace has an `AGENTS.md`, how many skills and plugins loaded, and the active personality. Beside or below it are your five most recent conversations. Click one to reopen it in place. A tip under the card changes every few seconds. A `art = [...]` list in `.symphony/dashboard.toml` replaces the logo. The card drops recent rows and padding to fit short terminals.

## The conversation

Type a request in the composer and press Enter. While a run is active, the transcript shows model output and tool activity; approval or question prompts appear when interaction is needed. Review changes in your project—the transcript is a record of activity, not a substitute for checking the result.

## Tool activity

Tool calls show up the way Grok Build's scrollback shows them:

- **Reading and searching fold.** A run of reads and searches becomes one row that counts what happened, such as `Read 3 files, Searched 2 patterns`. The verbs are present tense while a call is still running. Click the row, or press Enter on it, to list the calls; click a finished call to open its details.
- **Every other call keeps its own row**, such as `Update app.py +9 -0` or `Bash uv run pytest`. A running command shows its last output lines under the row. Click a finished row, or press Enter on it, to open its details: the diff, the command and its output, with search, wrap, and copy.
- **Long runs trim themselves.** Past 10 rows in a row, the older ones fold behind a row that counts them, such as `Edited 8 files, Ran 3 commands`. Click it to show them again.

Reads and edits count distinct files, so six edits to one file read `Edited 1 file`. When the run finishes, its work folds into a single summary above the final reply; subagents, generated images, and background jobs stay where they are.

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
