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
| `--resume --continue` | off | No picker: if the most recent session's last checkpoint is still `running` (the process was killed), continue it headless and unattended with one note naming the interruption time, stopped orphaned background jobs, and the original goal. Otherwise prints that there is nothing to continue. |
| `--unattended` | off | No human in the loop: auto-approve (`approvals.deny` still applies, also to children), auto-answer `ask_user`, no plan mode. Not a sandbox. |
| `--no-learning` | learning on | Disable post-run reflection |
| `--jev` | off | Enable the Jev finish check (does not switch the chat model) |

## symphony run

Headless unattended run of one task with your normal `~/.symphony` config,
credentials, and deny rules. The session is persisted to JSONL like a TUI
session; one log line per notable event goes to stdout.

```sh
uv run --package symphony-code symphony run --unattended [--detach] [--model ID] [--workspace PATH] "<task>"
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--unattended` | required | Acknowledges auto-approval (see `SECURITY.md`) |
| `--detach` | off | Re-exec in a new session with stdin closed, print pid, log path, and session id, write `~/.symphony/sessions/<sid>.run.json`, and exit. Output goes to `<sid>.run.log`. No daemon manager: stop it with `kill <pid>`. |
| `--model ID` | `last_model` / first available | `provider:model` id |
| `--workspace PATH` | `.` | Working directory |
| `--session-id ID` | new uuid | Session id to write |

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
| `--jev` | off | Enable the Jev finish check |

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
