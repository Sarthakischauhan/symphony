# Documentation

Find the guide for the task you came to do. Symphony is a Python workspace for building and running AI agents. Its packages are **not currently published on PyPI**; [install from source](./getting-started/installation.md).

## Run an agent

1. [Install the workspace](./getting-started/installation.md).
2. [Complete a first coding task](./getting-started/quickstart.md).
3. Choose a daily-use guide:

| Goal | Guide |
| --- | --- |
| Work in the terminal UI | [TUI and controls](./user-guide/tui.md) |
| Configure providers, models, and approvals | [Configuration](./user-guide/configuration.md) · [environment reference](./reference/environment.md) |
| Understand workspace tools and access | [Tools](./user-guide/tools.md) |
| Resume or protect saved conversations | [Sessions](./user-guide/sessions.md) |
| Use persistent learning | [Learning and memory](./user-guide/learning.md) |
| Enable voice, tracing, or completion checks | [Voice](./developer-guide/voice-mode.md) · [Langfuse](./user-guide/langfuse.md) · [Jev](./user-guide/jev.md) |
| Automate a run or use a browser | [CLI reference](./reference/cli.md) · [Browser agent](./packages/symphony-browser.md) |

## Build with the harness

| You need | Start here |
| --- | --- |
| Model providers and stream types | [symphony-core](./packages/symphony-core.md) |
| A reusable agent loop, tools, and events | [symphony-harness](./packages/symphony-harness.md) |
| A ready-to-run coding agent | [symphony-code](./packages/symphony-code.md) |
| A browser-use agent | [symphony-browser](./packages/symphony-browser.md) |
| An HTTP/SSE interface | [core-server](./packages/core-server.md) |

These are workspace packages, not currently installable PyPI releases. Package-specific READMEs provide short entry points; this `docs/` tree contains the guides.

## Develop Symphony

| Goal | Guide |
| --- | --- |
| Understand package boundaries and run lifecycle | [Architecture](./developer-guide/architecture.md) |
| Add product behavior to the harness | [Extending the harness](./developer-guide/extending.md) |
| Consume or change the event contract | [Event overview](./developer-guide/events.md) · [complete payload catalog](../core_harness/docs/events.md) |
| Work on learning or local extensions | [Learning pipeline](./developer-guide/learning-flow.md) · [Skills and plugins](./developer-guide/skills-and-plugins.md) |
| Work on terminal interface internals | [TUI architecture](../coding_agent/TUI_ARCHITECTURE.md) · [performance investigation](./developer-guide/tui-performance.md) |
| Contribute, run checks, or report a security issue | [AGENTS.md](../AGENTS.md) · [Security policy](../SECURITY.md) |
| Release packages to PyPI | [Publishing guide](./developer-guide/publishing.md) |

## Reference and project history

- [CLI commands and flags](./reference/cli.md)
- [Slash commands](./reference/slash-commands.md)
- [Environment variables](./reference/environment.md)
- [Changelog](../CHANGELOG.md)
- [Maintainer status and roadmap](../plan.md)
