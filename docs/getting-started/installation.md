# Install from source

Symphony is **not currently published on PyPI**. The supported way to try it today is to clone the repository and run its uv workspace. Do not use `pip install` or `uv add` for Symphony packages until this page announces a published release.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- An API key or supported provider login to run a model; you can set up a provider on first launch

## Clone and launch

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
uv run --package symphony-code symphony
```

The current directory is the default workspace. To open another project:

```sh
uv run --package symphony-code symphony --workspace /path/to/project
```

The commands `symphony`, `symphony-code`, and `coding-agent-tui` launch the same terminal application. Supported provider setup is covered in [Quickstart](./quickstart.md); full environment variables are in the [reference](../reference/environment.md).

## Use a workspace package as a library

The repository includes separate packages for providers (`core_ai`), the agent loop (`core_harness`), and the coding agent (`coding_agent`). They can be imported while working in this source checkout. For now, use the workspace rather than a package-index install:

```sh
uv sync
uv run python -c 'from core_harness import CoreHarness; print(CoreHarness)'
```

For a runnable example, see [Build with the harness](../packages/symphony-harness.md). Package and import names are listed in the [documentation index](../README.md#build-with-the-harness).

## Check the checkout

```sh
uv run pytest
```

Continue to the [quickstart](./quickstart.md) to configure a provider and complete a first task. PyPI instructions will be added here only when distributions are actually published.
