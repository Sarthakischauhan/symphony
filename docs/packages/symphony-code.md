# symphony-code

The ready-to-run coding product built on `symphony-harness`. It combines workspace tools, approval prompts, persistent sessions, and a Textual terminal UI. The Python import is `coding_agent`; the TUI command is `symphony`.

**Availability:** not currently published on PyPI. Run from a source checkout as described in the [installation guide](../getting-started/installation.md).

## Run a task

```sh
uv run --package symphony-code symphony --workspace /path/to/project
```

If no provider has been configured, first launch offers setup. The commands `symphony-code` and `coding-agent-tui` are aliases. Try a verifiable task in the [quickstart](../getting-started/quickstart.md).

## Use as a library

From the repository workspace:

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()
agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".")
result = await agent.run("Fix the failing test")
print(result.output_text)
```

The application manages provider setup, workspace tools, approval behavior, sessions, and UI. The reusable agent accepts a registry, model, and workspace; build other products directly on [symphony-harness](./symphony-harness.md).

## Choose a guide

- [Daily TUI use](../user-guide/tui.md) · [slash commands](../reference/slash-commands.md)
- [Configuration and approvals](../user-guide/configuration.md) · [tools](../user-guide/tools.md)
- [Sessions and resume](../user-guide/sessions.md) · [learning](../user-guide/learning.md)
- [CLI reference](../reference/cli.md) · [Security policy](../../SECURITY.md)
