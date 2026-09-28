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
| `--resume` | off | Pick a saved session interactively. Sessions still owned by a live Symphony process (`~/.symphony/active`) are hidden |
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

## symphony-browser

Browser-use agent. `CoreHarness.run` calls the browser tools and the model's
last message is the answer. Prints the JSON result.
Exit 0 when the run is `done`, 1 for `blocked` / `limited` / `error`, 2 for a
setup error (bad URL, no chat provider, Chromium missing, page failed to load).

```sh
uv run --package symphony-browser symphony-browser "what to do" [--url URL] [options]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `query` | required | The harness user message. Never put credentials here: it is emitted and written to the trace |
| `--url URL` | DuckDuckGo HTML search for the query (`https://html.duckduckgo.com/html/`) | Optional page to open. Only `http` / `https` with a host. The default avoids Google's bot interstitial; DuckDuckGo can still rate-limit |
| `--model ID` | `SYMPHONY_MODEL` or the first configured provider | `provider:model` for the harness loop |
| `--max-steps N` | `12` | Harness turn cap; hitting it ends as `limited` |
| `--headed` | off | Show the Chromium window |
| `--no-sandbox` | off | Disable the Chromium sandbox (and `/dev/shm`). Only for root or containers |
| `--trace PATH` | none | Also write the JSON result to `PATH` |

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
## symphony stdio

`symphony stdio --workspace /path/to/project [--session-id ID] [--model PROVIDER:MODEL]`
starts an interactive, one-turn-at-a-time JSONL agent process. A manager sends
`{"type":"run","prompt":"..."}` on stdin. Symphony sends a `ready` frame
with its persisted session ID, `event` frames with its control-plane events,
`input_requested` frames for approvals and questions, and a terminal `done`
frame. Reply with `{"type":"answer","request_id":"...","value":"..."}`;
`{"type":"interrupt"}` cancels the active turn. Use the returned session ID
on the next process to resume the conversation. Standard output is reserved
for protocol frames; diagnostics go to standard error.
`symphony stdio --models` prints one `models` frame for providers configured
on that machine, with Symphony's current default listed first.
The `run` command can include `"attachments":["/absolute/image.png"]`; the
transport embeds up to eight images in the user message.
`--unattended` applies Symphony's unattended policy: tool prompts are
auto-approved subject to deny rules, and user questions are auto-answered.
