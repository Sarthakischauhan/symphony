# CLI

## symphony

Textual coding-agent TUI. Aliases: `symphony-code`, `coding-agent-tui`,
`python -m coding_agent.tui`.

```sh
uv run --package symphony-code symphony [options]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--workspace PATH` | current directory | Working directory: relative paths, bash cwd, `.symphony` |
| `--model ID` | `SYMPHONY_MODEL` or first available provider | `provider:model` id |
| `--resume` | off | Pick a saved session interactively |
| `--no-learning` | learning on | Disable post-run reflection |

## core-server

```sh
uv run --package core-server core-server [options]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Bind port |
| `--model` | env / OpenAI default | Server default model id |
| `--system-prompt` | package default | Override the system prompt |

## Workspace tasks

```sh
uv sync
uv run pytest
uv run --package core-server pytest
uv run python scripts/generate_models.py   # from core_ai/
```
