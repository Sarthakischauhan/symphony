# Command-line reference

Use the [source installation guide](../getting-started/installation.md) before running these workspace commands. For the common interactive workflow, start with the [quickstart](../getting-started/quickstart.md).

## `symphony` terminal UI

The default command opens Symphony Code. `symphony-code` and `coding-agent-tui` are aliases.

```sh
uv run --package symphony-code symphony [options]
```

| Option | What it does |
| --- | --- |
| `--workspace PATH` | Choose the project working directory (default: current directory) |
| `--model ID` | Select a `provider:model` id |
| `--resume` | Choose a saved session |
| `--resume --continue` | Continue the latest interrupted session unattended |
| `--unattended` | Run without human prompts; see [Security](../../SECURITY.md) |
| `--no-learning` | Disable automatic learning for this process (learning is on by default) |
| `--jev` | Enable Jev findings (does not change the chat model) |

Daily controls are in the [TUI guide](../user-guide/tui.md); interactive commands are in the [slash-command reference](./slash-commands.md).

## `symphony run`: headless coding run

`symphony run` requires `--unattended`: it automatically handles approval prompts and human questions. Read the [security warning](../../SECURITY.md) before using it.

```sh
uv run --package symphony-code symphony run --unattended "Fix the failing test" \
  --workspace /path/to/project [--detach] [--model PROVIDER:MODEL]
```

`--detach` starts a background process and prints its pid, log path, and session id. Stop it with `kill <pid>`; it is not managed by a daemon service. Sessions are persisted like TUI sessions.

## `symphony skills` and `symphony plugins`

Manage skills and plugins without starting the TUI. A source is a local path, a git URL with an optional `@ref` (`https://github.com/o/r@v1`), `owner/repo` (GitHub), or for plugins `plugin@marketplace`. Installing copies files; it never runs plugin code. Exit code 0 on success, 1 on any error. The same commands exist as `/skills` and `/plugins` in the TUI and stdio.

```sh
symphony skills add owner/repo [--project] [--path DIR]
symphony skills list | remove NAME | enable NAME | disable NAME | update [NAME]
symphony skills mode NAME on|name-only|manual|default

symphony plugins add SOURCE [--path DIR]
symphony plugins list | remove NAME | enable NAME | disable NAME | update [NAME]
symphony plugins trust NAME [--revoke]
symphony plugins marketplace add SOURCE | list | update [NAME] | remove NAME
```

| Command | What it does |
| --- | --- |
| `skills add` | Install every `SKILL.md` under the source into `~/.symphony/skills/<name>`, or `.agents/skills/<name>` in the project with `--project` |
| `skills mode` | Set one skill's catalog mode; see [configuration](../user-guide/configuration.md#skills-and-plugins) |
| `skills list` | Name, mode, token cost, origin and path of each skill, plus the catalog total against `skills.max_context_tokens` |
| `plugins add` | Install into `plugins/cache/<marketplace>/<plugin>/<version>/` and print the skills added and every unsupported part skipped |
| `plugins trust` | Allow the plugin's addon code to run; the only command that records trust. `--revoke` withdraws it |
| `plugins marketplace add` | Register a catalog (`.agents/plugins`, `.claude-plugin` or `.cursor-plugin` `marketplace.json`) |
| `update` | Fetch again from the recorded source; plugin trust survives only if the addon is unchanged |

Details, trust and what loads: [skills and plugins](../developer-guide/skills-and-plugins.md).

## Other commands

### `symphony bench`

Headless benchmark run. It writes `workspace.patch` and `result.json`; exit 0 means the agent finished, not that an external grader accepted the result.

```sh
uv run --package symphony-code symphony bench \
  --workspace /testbed --instruction instruction.md
```

Set options with `--model`, `--max-turns`, `--timeout`, `--personality`, and `--jev`. Defaults may come from `bench/config.toml`. The [bench README](../../bench/README.md) describes the Harbor adapter.

### `symphony-browser`

Run a browser task in Chromium. Without `--url`, it searches DuckDuckGo HTML for the task; otherwise it opens the supplied HTTP(S) URL.

```sh
uv run --package symphony-browser playwright install chromium
uv run --package symphony-browser symphony-browser \
  "Find the first espresso article" --url https://example.com
```

Use `--model`, `--max-steps`, `--headed`, `--no-sandbox`, or `--trace PATH` as needed. Never put secrets in the task: it may appear in events and traces. The browser agent has no general website trust boundary; treat page content as untrusted input. See the [browser guide](../packages/symphony-browser.md).

### `core-server`

```sh
uv run --package core-server core-server [--host HOST] [--port PORT] \
  [--model PROVIDER:MODEL] [--system-prompt TEXT]
```

It binds to `127.0.0.1:8000` by default. The server has no built-in authentication; see the [server guide](../packages/core-server.md) before exposing it.

## Protocol hosts

These commands expose agent protocols over stdio for editor or process integrations. stdout is protocol data; do not mix application logs into it.

### `symphony stdio`

```sh
symphony stdio --workspace /path/to/project [--session-id ID] \
  [--model PROVIDER:MODEL] [--unattended]
```

A host sends JSONL `run` frames and receives `ready`, event, input-request, and `done` frames. Answer requests by id; use `interrupt` to cancel and `steer` to inject user input. The transport owns one active turn at a time. A `model/list` request returns models for configured providers. Run frames may include up to eight absolute image attachments. The [stdio protocol guide](../../coding_agent/src/coding_agent/protocols/stdio/README.md) documents the frame contract.

### `symphony acp`

```sh
symphony acp [--model PROVIDER:MODEL] [--unattended]
```

Starts the [Agent Client Protocol](https://agentclientprotocol.com) host (protocol version 1). It accepts new sessions and prompts, streams session updates, requests permission, and supports cancellation. It does not restore earlier sessions or accept image prompts. See the [ACP implementation guide](../../coding_agent/src/coding_agent/protocols/acp/README.md) for mappings and limits.

## Repository checks

From the repository root, run `uv sync`, `uv run pytest`, and `uv run ruff check .`. See [AGENTS.md](../../AGENTS.md) for development conventions.

## Symphony Web

`symphony web [--workspace PATH] [--model PROVIDER:MODEL] [--port PORT] [--no-browser]`
starts the local browser interface using the existing coding agent and TUI session
storage. See the [Web guide](../developer-guide/web.md) for operation, security,
and frontend/wheel build instructions.
