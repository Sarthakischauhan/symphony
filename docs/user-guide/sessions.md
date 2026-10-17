# Sessions

Symphony Code saves conversations so you can inspect or continue work later. Sessions can include messages, tool activity, images, checkpoints, and compaction data; treat the archive as private project data.

## Resume a session

From the repository workspace, open the session picker:

```sh
uv run --package symphony-code symphony --resume
```

You can also use `/new` in the TUI to begin a fresh conversation. The `/session` command inspects saved session information. See the [CLI reference](../reference/cli.md) for interrupted-run continuation options.

## Where data lives

By default, user-level data is stored below `~/.symphony/`; set `SYMPHONY_HOME` to use another home directory. Keep session archives out of version control and restrict access: they can contain prompts, private code, tool output, and image attachments.

Older JSONL sessions are migrated when accessed; the original file may be retained as a compatibility backup. Plan mode has been removed; sessions recorded in that mode must not silently resume with write-capable tools. Start a fresh conversation for new work. Do not edit active session files by hand.

## Use sessions in an application

The generic harness exposes conversation state and a session identifier, but persistent session storage is a product concern. See the [harness guide](../packages/symphony-harness.md) for continuing runs and the [event reference](../developer-guide/events.md) for run lifecycle events.
