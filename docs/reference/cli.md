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
| `--jev` | off | Enable the Jev finish check (does not switch the chat model) |

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

## symphony-browser

Browser-use agent. Jev chooses every operation and element; Grok writes text
only for `TYPE_TEXT` when the goal has no literal. Prints the JSON result.
Exit 0 when the run is `done`, 1 for `blocked` / `limited` / `error`, 2 for a
setup error (bad URL, bad Jev config, Chromium missing, page failed to load).

```sh
uv run --package symphony-browser symphony-browser demo [options]
uv run --package symphony-browser symphony-browser run --url URL --goal TEXT [options]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--url URL` | required (`run`) | Page to open. Only `http` / `https` with a host |
| `--goal TEXT` | required (`run`) | What to achieve. Never put credentials here: the goal is emitted, sent to Jev, and written to the trace |
| `--policy` | `auto` | `auto` (Jev if a key is set, else the offline fixture), `jev` (fail without a key), `fixture` |
| `--max-steps N` | `6` (`demo`), `12` (`run`) | Step cap; hitting it ends as `limited` |
| `--headed` | off | Show the Chromium window |
| `--no-sandbox` | off | Disable the Chromium sandbox (and `/dev/shm`). Only for root or containers |
| `--trace PATH` | none | Also write the JSON result to `PATH` |
| `--text-model grok:ID` | `SYMPHONY_BROWSER_TEXT_MODEL`, else the catalog Grok default | Text writer for `TYPE_TEXT`. Only `grok:` models; anything else exits 2 |

Install Chromium once with `uv run --package symphony-browser playwright install chromium`.

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
