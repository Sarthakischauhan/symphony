# Installation

Symphony is a [uv](https://docs.astral.sh/uv/) workspace of four Python packages.
The shipped product is **symphony-code** (the Textual TUI). The other packages
are libraries you can import on their own.

> **Requirements:** Python **3.11+** and uv. You need at least one provider
> credential. If none is set, the TUI walks you through choosing a provider
> and pasting an API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
> `GEMINI_API_KEY` / `GOOGLE_API_KEY`, or `XAI_API_KEY`).

## Install from source

This is the path that always works today. It installs the workspace, the TUI,
the harness, and the server together.

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
```

Then launch the TUI from the repo root:

```sh
uv run --package symphony-code symphony
```

If a key is already in the environment, that provider is used immediately.
Otherwise the TUI asks which provider to add.

`symphony`, `symphony-code`, and `coding-agent-tui` are aliases for the same
entry point.

## Install as a library

The three published packages are `symphony-core`, `symphony-harness`, and
`symphony-code`. `core-server` stays in the workspace for now. GitHub Releases
build wheels and upload them to PyPI.

```sh
uv add symphony-core
uv add symphony-harness
uv add symphony-code
```

```sh
pip install symphony-core symphony-harness symphony-code
```

PyPI names and import names differ on purpose:

| Package | Import | Install for |
| --- | --- | --- |
| `symphony-core` | `core_ai` | Providers, catalog, `Message` / `StreamEvent` |
| `symphony-harness` | `core_harness` | Agent loop, tools, control plane |
| `symphony-code` | `coding_agent` | Workspace tools + TUI (`symphony`) |
| `core-server` | `core_server` | FastAPI SSE server (workspace only) |

## Provider credentials

Every provider with a key is registered. Set keys in the environment,
`~/.symphony/.env`, a workspace `.env` (local override), or from the TUI:
first-run onboarding and `/provider`.


| Provider | Credential | Optional |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL`, `OPENAI_BASE_URL` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `GEMINI_MODEL`, `GEMINI_BASE_URL` |
| Grok | `XAI_API_KEY` | `GROK_MODEL` / `XAI_MODEL`, `XAI_BASE_URL` |

`SYMPHONY_MODEL` overrides all of the provider-specific model variables. Model
ids are `provider:model`, for example `anthropic:claude-sonnet-5`.

See the full [environment reference](../reference/environment.md).

## Verify the install

```sh
uv run pytest
```

If the TUI opens, shows a composer, and `/status` prints a model id, the
install is good. Next: the [Quickstart](./quickstart.md).
