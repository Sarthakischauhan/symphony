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

### Install (one-liner)

```sh
curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) if missing, then installs `symphony-code` from PyPI as a uv tool, pinned to the latest GitHub release. Re-running upgrades. macOS and Linux (x86_64/arm64) only; no sudo.

Prefer to inspect the script first:

```sh
curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh -o install.sh
less install.sh
sh install.sh
```

- Pin a version: `curl -fsSL .../install.sh | SYMPHONY_VERSION=0.0.1 sh`
- Uninstall: `curl -fsSL .../install.sh | sh -s -- --uninstall`

Then run `symphony --workspace /path/to/your/project`.

### From source (alternative)

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
uv run --package symphony-code symphony   # run your working tree; your installed symphony is untouched
uv run pytest
uv run ruff check .
```

Use `uv run --package symphony-code symphony` (`uv run symphony` after `uv sync --all-packages`) from the checkout for day-to-day development rather than `uv tool install -e .` or `uv tool install .`: an editable tool install makes your global `symphony` whatever branch is checked out. A source checkout or a local (`file://`) install never self-updates; only a uv tool install of the PyPI release does. The test suite isolates HOME, the XDG and uv tool directories, and fails if it changes your real `symphony`, uv tool directory or `~/.symphony`.

See [AGENTS.md](AGENTS.md) for contributor workflow and [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT. For vulnerability reporting and deployment guidance, see [SECURITY.md](SECURITY.md).
