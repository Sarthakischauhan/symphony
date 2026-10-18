# Install Symphony

Python 3.11 or newer is required. Version **0.0.1** of these three packages is published on PyPI:

| PyPI package | Import | What it is |
| --- | --- | --- |
| `symphony-core` | `core_ai` | Model providers and streaming types |
| `symphony-harness` | `core_harness` | Agent loop, tools, limits, and events |
| `symphony-code` | `coding_agent` | Coding agent and `symphony` terminal command |

`core-server` and `symphony-browser` are not published. Use them from a source checkout.

## Install a published package

```sh
python -m pip install symphony-code
symphony --workspace /path/to/project
```

`symphony-code` depends on `symphony-core` and `symphony-harness`, so that one install includes them. Install a library on its own when you do not want the coding agent:

```sh
python -m pip install symphony-core
python -m pip install symphony-harness
```

With uv, use `uv add symphony-code` in a project, or `uv tool install symphony-code` to put the `symphony` command on your PATH. `symphony`, `symphony-code`, and `coding-agent-tui` launch the same terminal application.

You also need credentials for a supported model provider. The first launch can guide that setup. See the [quickstart](./quickstart.md) and the [environment reference](../reference/environment.md).

**Safety:** workspace tools and shell commands run with your user permissions. Approval prompts are not a sandbox. Read [SECURITY.md](../../SECURITY.md) before using Symphony with an untrusted workspace or unattended.

## Work from source

Contributors, and anyone using `core-server` or `symphony-browser`, clone the workspace:

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
uv run --package symphony-code symphony --workspace /path/to/project
```

The current directory is the default workspace. Check the checkout with `uv run pytest`. The published 0.0.1 packages match the `v0.0.1` release; `main` can contain newer changes that are not on PyPI yet.
