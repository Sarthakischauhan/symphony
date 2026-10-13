<p align="center">
  <img src="docs/assets/symphony-logo.svg" alt="Symphony" width="420">
</p>

# Symphony

**An open-source Python harness for AI agents, with a coding agent ready to run.** Build an agent from composable model providers, tools, and a typed event stream—or use Symphony Code from your terminal.

> **Availability:** Symphony is not currently published on PyPI. Install and run it from the source workspace using the instructions below.

<p align="center">
  <a href="docs/getting-started/installation.md"><strong>Install from source</strong></a> ·
  <a href="docs/getting-started/quickstart.md"><strong>Try a coding task</strong></a> ·
  <a href="docs/README.md"><strong>Documentation</strong></a> ·
  <a href="https://github.com/Sarthakischauhan/symphony">GitHub</a>
</p>

## Run Symphony Code

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), and credentials for a supported model provider. The first launch can guide you through provider setup.

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
uv run --package symphony-code symphony --workspace /path/to/your/project
```

Ask it for a small change you can verify, such as adding a function and a test. Review tool actions and approval prompts. The [quickstart](docs/getting-started/quickstart.md) walks through a first run and follow-up tasks.

**Safety:** Workspace tools and shell commands run with your user permissions. Approval prompts are not a sandbox or filesystem boundary. Read [SECURITY.md](SECURITY.md) before using Symphony with an untrusted workspace or unattended.

## Build with Symphony

Symphony separates reusable agent infrastructure from products that use it:

- **`symphony-core`** (`core_ai`): provider integrations and model-neutral streaming types.
- **`symphony-harness`** (`core_harness`): agent turns, tools, limits, events, and extension hooks.
- **`symphony-code`** (`coding_agent`): workspace coding agent, terminal UI, and sessions.
- **`symphony-browser`** (`browser_agent`): browser-use agent.
- **`core-server`** (`core_server`): FastAPI interface for harness runs and events.

The names above identify components in the repository's uv workspace; **they are not PyPI install instructions**. Start at the [documentation index](docs/README.md) to find the right package guide, user guide, or API reference.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
```

See [AGENTS.md](AGENTS.md) for contributor workflow and [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT. For vulnerability reporting and deployment guidance, see [SECURITY.md](SECURITY.md).

<video src="docs/demo.mp4" controls muted loop playsinline poster="docs/demo.png" width="800">
  <a href="docs/demo.mp4">Watch Symphony create a Python file, add a test, and run pytest.</a>
</video>
