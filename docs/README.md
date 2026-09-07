# Symphony documentation

Symphony is an MIT-licensed agent harness. These pages are the user-facing docs
for every package in the workspace.

If you just want to run it:

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
uv run --package symphony-code symphony
```


Then read **[Installation](./getting-started/installation.md)** and
**[Quickstart](./getting-started/quickstart.md)**.

## Contents

| Section | What's covered |
| --- | --- |
| [Installation](./getting-started/installation.md) | Source install, library install, provider keys |
| [Quickstart](./getting-started/quickstart.md) | First TUI conversation, then a library run |
| [symphony-core](./packages/symphony-core.md) | Providers, catalog, streaming types |
| [symphony-harness](./packages/symphony-harness.md) | Loop, tools, events, limits, subagents |
| [symphony-code](./packages/symphony-code.md) | Workspace agent and TUI |
| [core-server](./packages/core-server.md) | FastAPI + SSE |
| [TUI](./user-guide/tui.md) | Composer, modes, keybindings, images |
| [Configuration](./user-guide/configuration.md) | `~/.symphony/config.json`, approvals, context |
| [Tools](./user-guide/tools.md) | Workspace tool surface |
| [Learning](./user-guide/learning.md) | Post-run reflection |
| [Sessions](./user-guide/sessions.md) | JSONL resume |
| [Architecture](./developer-guide/architecture.md) | How the four packages fit |
| [Changelog](../CHANGELOG.md) | 0.1.0 first-release notes |
| [Events](./developer-guide/events.md) | Control-plane catalog |
| [CLI](./reference/cli.md) | Flags for `symphony` and `core-server` |
| [Environment](./reference/environment.md) | Keys, models, base URLs |
| [Slash commands](./reference/slash-commands.md) | Every TUI command |

Package READMEs (`core_ai/`, `core_harness/`, `coding_agent/`, `core_server/`)
are the PyPI-facing versions of the same material. Prefer this `docs/` tree
when you are reading in GitHub.

| Directory | PyPI distribution | Python import | Command(s) |
| --- | --- | --- | --- |
| `core_ai/` | `symphony-core` | `core_ai` | — |
| `core_harness/` | `symphony-harness` | `core_harness` | — |
| `coding_agent/` | `symphony-code` | `coding_agent` | `symphony` (aliases `symphony-code`, `coding-agent-tui`) |
| `core_server/` | `core-server` (workspace only) | `core_server` | `core-server` |
