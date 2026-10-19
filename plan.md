# Project status and roadmap

This file is the maintainer's snapshot of what exists and what remains. It is not an installation guide: run Symphony from the repository workspace using the [installation guide](docs/getting-started/installation.md). Package release availability is stated in the package guides and should be checked there before installing.

## Current system

Symphony is a Python workspace with replaceable model providers, a reusable agent loop, and separate consumers. Its primary entry point is Symphony Code, a terminal coding agent. The harness can also be consumed by the browser agent and HTTP server.

| Workspace component | Import | Workspace command | Responsibility |
| --- | --- | --- | --- |
| `core_ai/` | `core_ai` | — | Providers, model catalog, shared stream types |
| `core_harness/` | `core_harness` | — | Agent loop, tools, events, limits, extensions |
| `coding_agent/` | `coding_agent` | `symphony` | Coding tools, approvals, sessions, terminal UI |
| `browser_agent/` | `browser_agent` | `symphony-browser` | Browser-use agent |
| `core_server/` | `core_server` | `core-server` | HTTP/SSE interface |

`symphony-core`, `symphony-harness`, and `symphony-code` 0.0.1 are published on PyPI. This checkout can be ahead of that release. `core-server` and `symphony-browser` are not published.

## Design constraints

- Keep provider-specific behavior behind the `core_ai` contracts.
- Keep workspace, terminal, and coding-product assumptions out of `core_harness`.
- Drive UIs and transports from typed events, not scraped stdout.
- Make tool capabilities and trust boundaries explicit; approval is not sandboxing.
- Document shipped behavior separately from proposals and backlog.

See [Architecture](docs/developer-guide/architecture.md), [Security](SECURITY.md), and [Contributing](AGENTS.md) for maintained guidance.

## Backlog

The following are directions, not promises or currently shipped behavior. Confirm with maintainers before taking on an item.

- Publish and document supported packages on PyPI; add tested versioned install instructions when that happens.
- Improve usability and operational tooling for long-running and unattended agent sessions.
- Continue evaluating provider compatibility and catalog refresh workflows.
- Symphony Web: if the chat SDK adds adapter subscriptions and mid-run widget answers, move to the full `Chat` component. The composer props and token-driven widget chrome from chat-sdk#34 are already in use.

Update this page when a concrete roadmap item is selected; detailed implementation plans belong with the associated work, not in the user documentation.
