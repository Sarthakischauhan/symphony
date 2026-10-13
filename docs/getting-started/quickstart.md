# Your first coding task

This walkthrough takes you from a source checkout to a change you can inspect on disk. If Symphony is not installed yet, follow [Install from source](./installation.md) first.

## 1. Start in the project you want to edit

From the Symphony repository, launch it with your target workspace:

```sh
uv run --package symphony-code symphony --workspace /path/to/project
```

On first launch, add a provider when prompted, or set an API key before starting. For example:

```sh
export OPENAI_API_KEY=sk-...
uv run --package symphony-code symphony --workspace /path/to/project
```

Keys entered during onboarding are stored under `~/.symphony`; see [provider configuration](../user-guide/configuration.md) before changing how credentials are stored.

## 2. Ask for a checkable change

Try a small task with an obvious result:

```text
Create hello.py with a greet() function and a test, then run the test.
```

Read the proposed actions. Symphony may ask before running shell commands or overwriting files. Inspect the resulting diff and test output yourself; a model's completion message is not proof that a task is correct.

## 3. Use the controls

- Type `/` to discover slash commands; `/model` selects a model.
- Type `/mode` to switch between build and plan modes.
- Type `@` at the end of a workspace-path mention to get file suggestions.
- Press `Esc` or `Ctrl+X` to cancel an active run.
- Press `Ctrl+B` to open the agent dashboard; `Ctrl+G` opens subagent sessions.

The [TUI guide](../user-guide/tui.md) explains the transcript and keyboard controls. The [tool guide](../user-guide/tools.md) describes what the agent can do in your workspace.

## 4. Continue later

Start the session picker with:

```sh
uv run --package symphony-code symphony --resume
```

Session storage and recovery options are explained in [Sessions](../user-guide/sessions.md).

## Next steps

- [Configure providers, approvals, and defaults](../user-guide/configuration.md)
- [Read the CLI reference](../reference/cli.md)
- [Build a custom agent with the harness](../packages/symphony-harness.md)
