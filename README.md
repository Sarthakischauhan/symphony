<p align="center">
  <img src="docs/assets/symphony-logo.svg" alt="Symphony" width="420">
</p>

<p align="center">
  <strong>An open-source coding agent for your terminal, and the Python harness it's built on.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/symphony-code/"><img alt="symphony-code on PyPI" src="https://img.shields.io/pypi/v/symphony-code?label=symphony-code"></a>
  <a href="https://pypi.org/project/symphony-harness/"><img alt="symphony-harness on PyPI" src="https://img.shields.io/pypi/v/symphony-harness?label=symphony-harness"></a>
  <a href="https://pypi.org/project/symphony-core/"><img alt="symphony-core on PyPI" src="https://img.shields.io/pypi/v/symphony-core?label=symphony-core"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

<p align="center">
  <a href="docs/getting-started/installation.md">Install</a> ·
  <a href="docs/getting-started/quickstart.md">Quickstart</a> ·
  <a href="docs/README.md">Docs</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

**Symphony Code** is a coding agent that runs in your terminal. Describe a
change and it reads the project, edits files, and runs your tests. It asks
before running shell commands or overwriting files.

Use any model you have: an API key, a ChatGPT, Claude, or Grok subscription, or a
model running locally.

```sh
curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh | sh
symphony --workspace /path/to/your/project
```

## Why Symphony

- **Any model.** Anthropic, OpenAI, Gemini, Grok, OpenRouter, Vercel AI Gateway,
  Ollama, or any OpenAI-compatible server (LM Studio, vLLM, llama.cpp). Switch
  mid-session with `/model`.
- **Use your subscription.** Sign in with ChatGPT, Claude, or Grok through
  `/login` instead of paying per token.
- **You stay in control.** Approval prompts before shell commands, file
  overwrites, and web searches. Inspect the workspace diff any time with `/diff`.
- **Sessions that last.** Every conversation is saved. Resume one with
  `--resume`, or let an interrupted run pick up from its checkpoint.
- **It learns how you work.** Corrections and preferences are kept as memory you
  can read and edit with `/learning`. Turn it off with `--no-learning`.
- **Subagents.** The agent can hand bounded tasks to child agents. Watch or steer
  them with `Ctrl+G`.
- **Agent profiles.** Put a model, instructions, and a tool allowlist in a YAML
  file (`reviewer`, `docs-writer`, …) and select it with `--profile`.
- **Extensible.** Install skills and plugins from a path, a git URL, or a
  marketplace. Add themes, tools, and lifecycle hooks.
- **Terminal, browser, or headless.** Use the TUI, `symphony web` for a local
  browser UI, or `symphony run --unattended` for scripts and CI.

## Get started

**Requirements:** macOS or Linux, Python 3.11+, and access to a model provider.

### 1. Install

```sh
curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh | sh
```

The script installs [uv](https://docs.astral.sh/uv/) if you don't have it, then
installs `symphony-code` from PyPI as a uv tool. You don't need sudo, and running it
again upgrades. To read the script before running it:

```sh
curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh -o install.sh
less install.sh && sh install.sh
```

Pin a version with `SYMPHONY_VERSION=<version> sh install.sh`, and uninstall with
`sh install.sh --uninstall`. If you'd rather use pip, run `pip install symphony-code`.
The [installation guide](docs/getting-started/installation.md) covers every option.

### 2. Launch it in a project

```sh
symphony --workspace /path/to/your/project
```

On first launch, Symphony walks you through connecting a provider. You can also
export a key such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` before you start.

### 3. Give it a task you can check

```text
Create hello.py with a greet() function and a test, then run the test.
```

Watch the tool calls, answer any approval prompts, and look at the diff. The
[quickstart](docs/getting-started/quickstart.md) walks through a first session.

### Everyday controls

| Do this | How |
| --- | --- |
| Browse commands | Type `/` |
| Mention a file | Type `@` |
| Switch model | `/model` |
| Add or change credentials | `/login` |
| Cancel a run | `Esc` or `Ctrl+X` |
| Open the agent dashboard | `Ctrl+B` |
| Open subagent sessions | `Ctrl+G` |
| Resume a past session | `symphony --resume` |

More: [TUI guide](docs/user-guide/tui.md) · [slash commands](docs/reference/slash-commands.md) · [CLI reference](docs/reference/cli.md) · [configuration](docs/user-guide/configuration.md)

## A note on safety

Symphony runs tools and shell commands **with your user permissions**. Approval
prompts help you review actions, but they are not a sandbox, and the workspace
is not a path jail. Read [SECURITY.md](SECURITY.md) before you point Symphony at a
workspace you don't trust or run it unattended.

## Build your own agent

Symphony Code runs on **Symphony Harness**, an agent runtime that has no
built-in knowledge of files or terminals. You can use it to build agents that
have nothing to do with code. Each layer is published on its own:

| Package | Import | What it gives you |
| --- | --- | --- |
| [`symphony-core`](docs/packages/symphony-core.md) | `core_ai` | Provider adapters and one model-neutral streaming API |
| [`symphony-harness`](docs/packages/symphony-harness.md) | `core_harness` | The agent runtime: tool calling, subagents, context compaction, session persistence, run limits, add-on hooks, typed events |
| [`symphony-code`](docs/packages/symphony-code.md) | `coding_agent` | The coding agent, its workspace tools, sessions, and terminal UI |
| [`symphony-browser`](docs/packages/symphony-browser.md) | `browser_agent` | A browser-use agent *(source only)* |
| [`core-server`](docs/packages/core-server.md) | `core_server` | Harness runs and events over HTTP/SSE *(source only)* |

A tool-using agent in a few lines:

```python
import asyncio
from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, HarnessConfig, Tool

def read_text(path: str) -> str:
    """Read a UTF-8 text file."""
    with open(path, encoding="utf-8") as f:
        return f.read()

async def main() -> None:
    registry = build_default_registry()
    harness = CoreHarness(
        registry=registry,
        model_id=default_model_id(registry),
        system_prompt="Answer concisely. Use tools when useful.",
        config=HarnessConfig(),
        tools=[Tool(read_text)],
    )
    result = await harness.run("Summarize README.md")
    print(result.output_text)

asyncio.run(main())
```

The harness has no product-specific logic. It runs the tools you register and
emits a typed event stream for UIs and servers to consume. See the
[architecture](docs/developer-guide/architecture.md),
[extension hooks](docs/developer-guide/extending.md), and
[event reference](docs/developer-guide/events.md).

## Contributing

Symphony is a [uv](https://docs.astral.sh/uv/) workspace.

```sh
git clone https://github.com/Sarthakischauhan/symphony && cd symphony
uv sync
uv run --package symphony-code symphony   # run your working tree
uv run pytest                             # no provider keys needed
uv run ruff check .
```

When you're developing, use `uv run` from the checkout instead of
`uv tool install -e .`, because an editable tool install makes your global
`symphony` point at whatever branch you have checked out. Commits follow
[Conventional Commits](https://www.conventionalcommits.org/). Read
[AGENTS.md](AGENTS.md) for the full workflow and [plan.md](plan.md) for the roadmap.

## License

[MIT](LICENSE). Report vulnerabilities as described in [SECURITY.md](SECURITY.md).
