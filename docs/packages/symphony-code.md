# symphony-code

`symphony-code` is the first product on the harness. It is not the harness. It
adds workspace tools, SQLite sessions, optional learning, and a
conversation-first Textual TUI driven entirely from control-plane events.

```sh
uv run --package symphony-code symphony
```

```sh
uv add symphony-code
```

Import it as `coding_agent`. `symphony`, `symphony-code`, and
`coding-agent-tui` are the same TUI entry point.

<div align="center">
  <img src="../demo.png" alt="Symphony TUI" height="340">
</div>

## What it provides

- Workspace tools: `read_file`, `write_file`, `generate_image`, `patch`,
  `search`, `bash`, `spawn_agent`, `ask_user`.
- Incremental repo discovery — no preloaded semantic index.
- Persisted conversations in SQLite, resumable by `session_id` or `--resume`.
- Optional learning/reflection after successful runs.
- Textual TUI with streaming Markdown, live tool events, reasoning summaries,
  usage, and compaction notices.

## Programmatic agent

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()
agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".",
)
result = await agent.run("Fix the failing test")
```

The agent asks before `bash`, overwriting an existing file, or applying a
broad patch. Plan-mode reads stay unprompted. Default run caps: 24 turns, 40
tool calls, 10 minutes, no aggregate token failure limit.

<div align="center">
  <img src="../subagent-spawn.gif" alt="Spawned subagent nested session" height="300">
</div>

`spawn_agent` opens a nested session with the same transcript chrome.

Guides:

- [TUI](../user-guide/tui.md)
- [Configuration](../user-guide/configuration.md)
- [Tools](../user-guide/tools.md)
- [Learning](../user-guide/learning.md)
- [Sessions](../user-guide/sessions.md)
- [Slash commands](../reference/slash-commands.md)
