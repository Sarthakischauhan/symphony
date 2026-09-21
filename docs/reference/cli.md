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
| `--jev` | off | Enable Jev critic mode (findings + optional message; does not switch the chat model) |

## symphony bench

Headless, non-interactive run. Same `CodingAgent` / harness `run()` as the TUI.
Keys come from the environment. Writes `workspace.patch` and `result.json` in
the workspace. Exit 0 means the agent finished; a grader owns pass/fail.

```sh
uv run --package symphony-code symphony bench --workspace /testbed --instruction instruction.md
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--workspace PATH` | `/testbed` if present, else `.` | Working directory |
| `--instruction PATH` | stdin (`-`) | Instruction file, or `-` for stdin |
| `--model ID` | `bench/config.toml` / env | `provider:model` id |
| `--max-turns N` | pinned in `bench/config.toml` | Harness turn cap |
| `--timeout SEC` | pinned in `bench/config.toml` | `max_runtime_seconds` |
| `--personality` | `direct` | `direct` or `precise` only (no picker) |
| `--jev` | off | Enable Jev critic mode |

Harbor adapter and image: [`bench/README.md`](../../bench/README.md).

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
