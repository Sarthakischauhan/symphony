# Working in this repository

Guidance for coding agents (and humans) making changes to Symphony.

## What this is

A [uv](https://docs.astral.sh/uv/) workspace of four Python packages. Names
differ by layer on purpose; use the right one for the context you are in:

| Directory | PyPI distribution | Python import | Command(s) |
| --- | --- | --- | --- |
| `core_ai/` | `symphony-core` | `core_ai` | — |
| `core_harness/` | `symphony-harness` | `core_harness` | — |
| `coding_agent/` | `symphony-code` | `coding_agent` | `symphony` (aliases `symphony-code`, `coding-agent-tui`) |
| `core_server/` | `core-server` (not published) | `core_server` | `core-server` |

Dependency direction is strictly `core_ai` → `core_harness` → `coding_agent` /
`core_server`. The harness must stay product-agnostic: anything that knows
about files, shells, TUIs, or session files belongs in `coding_agent`, not
`core_harness`.

## Commands

```sh
uv sync                    # install all workspace packages + dev tools (locked)
uv run pytest              # every suite; or pass a package's tests/ dir
uv run ruff check .        # lint; CI runs exactly this
uv build --package symphony-core -o dist   # same build CI and releases run
uv run --package symphony-code symphony    # launch the TUI
```

Tests do not need provider keys. Keep it that way: mock providers, never call
a live API from a test.

## Conventions

- One tool per file under `coding_agent/src/coding_agent/tools/`, subclassing
  `WorkspaceTool`. Relative paths start at the working directory; absolute
  and `~` paths are allowed. There is no path jail. Do not describe this as
  a sandbox.
- UIs consume control-plane events; they never scrape stdout. If you add or
  rename a harness event, update `ControlPlaneEventType` in
  `core_harness/src/core_harness/models.py` **and** both event docs
  (`docs/developer-guide/events.md`, `core_harness/docs/events.md`).
- `core_ai/src/core_ai/models/generated.py` is a generated snapshot. Do not
  edit it by hand and do not make anything regenerate it on install or build.
  Refresh it deliberately with `cd core_ai && uv run python scripts/generate_models.py`
  and commit the result.
- Approval prompts, `bash` execution, and subagent spawning form the trust
  model of `symphony-code`. Changes there are behavioural, not cosmetic;
  discuss them before making them and update `SECURITY.md` if the guarantees
  change.
- Docs describe what is in the tree today. Roadmap items go in `plan.md`
  under "Open backlog", not into README feature tables.
- Lint rules are the correctness-only ruff set in the root `pyproject.toml`.
  Fix violations rather than adding ignores.

## Where things are documented

- `README.md` — overview, install, names table
- `docs/` — user and developer docs (the canonical versions)
- `<package>/README.md` — PyPI-facing copies; keep them consistent with `docs/`
- `plan.md` — what exists, what is next
- `SECURITY.md` — reporting and the current trust model
