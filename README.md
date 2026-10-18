<p align="center">
  <img src="docs/assets/symphony-logo.svg" alt="Symphony" width="420">
</p>

# Symphony

**An open-source Python harness for AI agents, with a coding agent ready to run.** Build an agent from composable model providers, tools, and a typed event stream—or use Symphony Code from your terminal.

> **Availability:** `symphony-core`, `symphony-harness`, and `symphony-code` **0.0.1** are on PyPI. `core-server` and `symphony-browser` remain source-only.

<p align="center">
  <a href="docs/getting-started/installation.md"><strong>Install</strong></a> ·
  <a href="docs/getting-started/quickstart.md"><strong>Try a coding task</strong></a> ·
  <a href="docs/README.md"><strong>Documentation</strong></a> ·
  <a href="https://github.com/Sarthakischauhan/symphony">GitHub</a>
</p>

## Run Symphony Code

**Requirements:** Python 3.11+ and credentials for a supported model provider. The first launch can guide you through provider setup.

```sh
python -m pip install symphony-code
symphony --workspace /path/to/your/project
```

`symphony-code` installs `symphony-core` and `symphony-harness` with it. The full options, including a source checkout, are in the [installation guide](docs/getting-started/installation.md).

Ask it for a small change you can verify, such as adding a function and a test. Review tool actions and approval prompts. The [quickstart](docs/getting-started/quickstart.md) walks through a first run and follow-up tasks.

**Safety:** Workspace tools and shell commands run with your user permissions. Approval prompts are not a sandbox or filesystem boundary. Read [SECURITY.md](SECURITY.md) before using Symphony with an untrusted workspace or unattended.

## Build with Symphony

Symphony separates reusable agent infrastructure from products that use it:

- **`symphony-core`** (`core_ai`): provider integrations and model-neutral streaming types.
- **`symphony-harness`** (`core_harness`): agent turns, tools, limits, events, and extension hooks.
- **`symphony-code`** (`coding_agent`): workspace coding agent, terminal UI, and sessions.
- **`symphony-browser`** (`browser_agent`): browser-use agent.
- **`core-server`** (`core_server`): FastAPI interface for harness runs and events.

Install the first three from PyPI: `pip install symphony-core`, `pip install symphony-harness`, or `pip install symphony-code`. `symphony-browser` and `core-server` are workspace-only. Start at the [documentation index](docs/README.md) for the package, user, and API guides.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
```

See [AGENTS.md](AGENTS.md) for contributor workflow and [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT. For vulnerability reporting and deployment guidance, see [SECURITY.md](SECURITY.md).
