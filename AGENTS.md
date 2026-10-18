# Working in this repository

Guidance for coding agents (and humans) making changes to Symphony.

## What this is

A [uv](https://docs.astral.sh/uv/) workspace of five Python packages. Names
differ by layer on purpose; use the right one for the context you are in:

| Workspace directory | Import | Workspace command |
| --- | --- | --- |
| `core_ai/` | `core_ai` | — |
| `core_harness/` | `core_harness` | — |
| `coding_agent/` | `coding_agent` | `symphony` (`symphony-code`, `coding-agent-tui` aliases) |
| `core_server/` | `core_server` | `core-server` |
| `browser_agent/` | `browser_agent` | `symphony-browser` |

`symphony-core`, `symphony-harness`, and `symphony-code` 0.0.1 are on PyPI.
`core-server` and `symphony-browser` are not. See the
[installation guide](docs/getting-started/installation.md). Do not document a
newer PyPI release until it has actually been uploaded.

Dependency direction is strictly `core_ai` → `core_harness` → `coding_agent` /
`core_server` / `browser_agent`. The harness must stay product-agnostic: anything that knows
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

- `README.md` — project overview and source-install path
- `docs/` — canonical user, package, developer, and reference guides; start at `docs/README.md`
- `<package>/README.md` — concise package entry points that link to the canonical guides; keep release instructions accurate
- `plan.md` — current implementation status and open backlog
- `SECURITY.md` — vulnerability reporting and the current trust model
