# Symphony Plan

What is in the tree today, and what is next. Everything in "Current state" is
verifiable against `main`; anything not yet built lives under "Open backlog".
Update this file in the PR that changes the facts.

| Directory | PyPI distribution | Python import | Command(s) |
| --- | --- | --- | --- |
| `core_ai/` | `symphony-core` | `core_ai` | — |
| `core_harness/` | `symphony-harness` | `core_harness` | — |
| `coding_agent/` | `symphony-code` | `coding_agent` | `symphony` (aliases `symphony-code`, `coding-agent-tui`) |
| `core_server/` | `core-server` (workspace only) | `core_server` | `core-server` |

---

## 1. Goal

Ship a reusable agent stack where the harness is product-agnostic and every
UI is driven by one typed control-plane event stream. The plane observes,
drives, and authorizes; it does not persist, compact, or spawn.

| Layer | Package | Role |
| --- | --- | --- |
| Providers | `core_ai` | Provider registry, generated model catalog, `Message` / `StreamEvent` |
| Loop | `core_harness` | Multi-turn tool loop, control plane, limits, compaction, add-ons, subagents |
| Product | `coding_agent` | Workspace coding agent (tools, JSONL sessions, Textual TUI, learning) |
| Transport | `core_server` | FastAPI wrapper that streams harness events over SSE |

---

## 2. Current state

### `core_ai` (symphony-core)

- Providers: OpenAI (Responses and Chat Completions, plus `gpt-image-*`),
  Anthropic Messages, Gemini `streamGenerateContent`, Grok Chat Completions.
  All translate to the shared `StreamEvent` contract, including
  `reasoning_delta` and retry signals (429, SSL MAC, 5xx, connection).
- `build_default_registry()` registers every provider with a credential;
  `default_model_id()` resolves `SYMPHONY_MODEL`, provider-specific overrides,
  then the first registered provider.
- Canonical text/image `Message.content` parts translated per provider.
- Model catalog: `src/core_ai/models/generated.py` is a checked-in snapshot
  produced from models.dev by `scripts/generate_models.py`. It records id,
  provider, API family, reasoning flag, and effort levels. Installing or
  building the package ships the snapshot unchanged; a refresh is an explicit
  maintainer action (`CORE_AI_REFRESH_CATALOG=1` opts one build in).

### `core_harness` (symphony-harness)

- `CoreHarness.run()` coordinates a run; `loop/` holds `TurnRunner`, tool-call
  execution, stream handling, and the run session; `context/` holds
  `HarnessState`, token estimates, pruning, and the keep/drop planner.
- Tool protocol: every call ends `success`, `error`, `timeout`, or
  `cancelled`; results are bounded at insert time; stale tool bodies can be
  pruned on a copy of the conversation.
- Control plane: one object, three jobs — observe (`emit`), drive
  (`send_command` / cancel / pause / inject), authorize
  (`approve_tool_call` / `request_user_input`). Base methods fail closed.
  `EventControlPlane` is the unattended default (record events, allow tools).
  `IdentifiedControlPlane` stamps `run_id`, `session_id`, `seq`, `ts`,
  `schema_version`, `agent_id`, `parent_id`. Event catalog:
  `ControlPlaneEventType` (run/turn lifecycle, deltas, tools, usage,
  context, compaction, pause/resume, injection, `agent_*`).
- Limits: `max_turns`, `max_tool_calls`, `max_runtime_seconds`, `max_tokens`
  → `run_limit_exceeded` / `HarnessLimitExceeded`. Cancellation stops model
  streams and tools and emits `run_cancelled`.
- Add-ons (`Addon` with `before_turn` / `after_turn` / `on_tool` /
  `on_compact` / `fork_for_child`): `PersistenceAddon`, `CompactionAddon`
  (+ template `KeepSystemRecentCompactor` and exported `plan_keep_drop`),
  `SubagentAddon`. There is no telemetry exporter and no skill loader.
- Subagents: `CoreHarness.spawn()` / `spawn_agent`; lifecycle events on the
  parent plane; child events tagged with `agent_id` / `parent_id`; parallel
  children (up to three per turn); `max_spawn_depth`.
- Parallel tool execution for tools that opt in (`max_parallel_tool_calls`).
- Approval gate: an interactive plane can implement `approve_tool_call` and
  `request_user_input`; the harness calls the gate before invoking a tool.

### `coding_agent` (symphony-code)

Tools, one module each under `WorkspaceTool` (`tools/base.py`), which binds a
working directory for relative paths and generates pydantic schemas. Absolute
and `~` paths are allowed:

| Tool | Module | Purpose |
| --- | --- | --- |
| `read_file` | `tools/read_file.py` | Read text (with line numbers) or images |
| `write_file` | `tools/write_file.py` | Create / overwrite text |
| `patch` | `tools/patch.py` | Exact-text edit; a miss returns nearby lines |
| `bash` | `tools/bash.py` | Async shell in the workspace (streamed, capped, timed out) |
| `search` | `tools/search.py` | File name / content search, `.gitignore`-aware |
| `generate_image` | `tools/generate_image.py` | Generate an image and write it to a path |
| `ask_user` | `tools/ask_user.py` | Clarifying questions through the control plane |
| `spawn_agent` | via `SubagentAddon` | Focused child agent |

- Default add-ons (`agent.default_addons`): `PersistenceAddon` (JSONL),
  `AiCompactionAddon` (`InferenceCompactor`: harness keep/drop plan + a
  model-written summary of dropped work), `SubagentAddon`.
- Approvals (`coding_agent.approvals.ApprovalPolicy` + `ApprovalConfig`):
  ask before `bash`, overwrite, or a broad patch; `always_allow` mode;
  allow-once answers. The TUI renders the question; it does not own the
  rules. Children still run without per-tool prompts (`SECURITY.md`).
- Config: `.symphony/config.json` → `CodingAgentConfig` (harness, approvals,
  tools, learning, compaction). Defaults: 24 turns, 40 tool calls, 10 minutes.
- Credentials: environment, workspace `.env`, `~/.symphony/.env`; first-run
  onboarding and `/provider` write the global file.
- Learning: after a run, `LearningLoop` asks the active model to review the
  transcript (capped at 900 output tokens), emits a two-line `run_summary`,
  and stores sanitized lessons in `.symphony/learning/lessons.jsonl` (bounded,
  atomic rewrite). Prior lessons are injected into later system prompts as
  historical notes. Disable with `--no-learning` / `learning.enabled=false`.
- Plan mode (`plan.py`): `Tab` toggles build / plan; plans are saved under
  `.symphony/plans/`.
- Textual TUI (`tui/`): streamed transcript with reasoning and tool panels,
  `@path` completion, slash commands (`/model`, `/mode`, `/effort`, `/plan`,
  `/provider`, `/new`, `/reload`, `/compact`, `/status`, `/context`,
  `/learning`, `/diff`, `/clear`, `/help`, `/quit`), context footer, image
  rendering, subagent cards and nested screens, session resume (`--resume`),
  `Esc` / `Ctrl+X` cancel. See `coding_agent/TUI_ARCHITECTURE.md`.

### `core_server` (core-server)

- `POST /runs` streams control-plane events as SSE with
  `id: <run_id>:<seq>`; `GET /models` returns the Chat SDK registry shape and
  `/runs` rejects unadvertised slugs; `GET /health`.
- Request-body, message, and history limits; bounded SSE queue; client
  disconnect sends the harness cancel command.
- CORS denies browser origins by default; no built-in authentication.
- `ask_user` is opt-in until the server supports responding to a running run.
- Not published to PyPI.

### Repository

- CI (`.github/workflows/ci.yml`): ruff lint, full test suite against the
  installed workspace packages, and a build of the three published packages;
  actions and uv pinned. Releases publish via trusted publishing
  (`publish.yml`).
- MIT licensed (`LICENSE`); vulnerability reporting in `SECURITY.md`;
  contributor conventions in `AGENTS.md`.

---

## 3. Design principles

1. **One tool per file.** Same shape everywhere (`WorkspaceTool` + `run` + register).
2. **Harness stays product-agnostic.** Coding-agent specifics live in `coding_agent`.
3. **Working directory, not a jail.** Relative paths and bash cwd start at
   the launch directory. Absolute and `~` paths are allowed. Approval prompts
   gate `bash`, overwrites, and broad patches. There is no container or
   OS-level isolation; do not describe one.
4. **Control plane for UX.** UIs subscribe to events; nothing scrapes stdout.
5. **Tests without keys.** Providers are mocked; no test calls a live API.
6. **Generated code is script-owned.** `generated.py` is refreshed by a
   maintainer command, never as a side effect of install or build.

---

## 4. Open backlog

Nothing below exists in the tree yet. Items under **Symphony-later** are
specified so a later `symphony` run on this repo can implement them; they are
not part of 0.1.0.

### Symphony-later

These are product features the agent can build on itself after 0.1.0 ships.
Do not start them in the release cut. Each item is one focused PR.

**Durable memory.** Today `LearningStore` appends
`.symphony/learning/lessons.jsonl` and injects the most recent lessons into
the next system prompt. There is no retrieval and no curated playbook.

- Keep the JSONL lesson log as the source of truth. Do not add a vector
  database for the first version of this work.
- Select lessons by task overlap (simple token/overlap score is enough),
  not "last N".
- Add a periodic synthesis pass that consolidates many lessons into
  `.symphony/learning/playbook.md` and injects that instead of the raw tail.
- Add a reviewed/trusted flag on a lesson. Unreviewed lessons stay
  available but ranked below reviewed ones.
- Tests: mock the provider; never call a live API.

**Skills / plugin add-on.** Today add-ons are constructed in Python and
passed to `CoreHarness`. There is no directory discovery.

Detailed implementation and acceptance criteria:
[Skills and plugins plan](coding_agent/skills-plugins-plan.md).

- Discover skill metadata under `.symphony/skills/` and `~/.symphony/skills/`;
  a product `SkillsAddon` supplies the catalog and explicit read-only skill roots.
  Reuse `read_file` for instructions and references; add no skill-loading tools.
  Extend only its read boundary, keeping writes and other tools unchanged.
- Add local plugin manifests that package skills and optional existing-style
  addon factories. Resolve plugins in `coding_agent` before harness construction;
  do not introduce another runtime or replace the control plane.
- Keep skills as instruction resources. Never import Python or execute scripts
  merely because a skill was discovered or loaded.
- Require explicit enablement and host authorization before importing executable
  plugins. Discuss this trust-model addition before implementation and update
  `SECURITY.md` when shipped. Model-facing actions retain existing approval paths.
- Deliver skill resources, agent integration, local plugin loading, and docs in
  focused phases. Remote installation, marketplaces, and hot reload are deferred.

**Compaction as a view.** Today compaction rewrites message entries in the
JSONL session. The TUI already hides compacted context from the transcript.

- Append a `compaction` record (summary + which messages dropped). Never
  delete user-visible messages from the log.
- `load_conversation` for the model projects the compact view (Pi-style
  `convertToLlm`). Resume and the TUI read the full log.
- Token deltas stay unstored.

**Control-plane remainder.** 0.1.0 names the three jobs and pulls policy out
of the TUI. Do not split `ControlPlane` into three packages or make it an
add-on.

- Typed authorization request/decision objects (allow/deny/reason, no
  implicit approve on empty/cancel).
- Per-run question IDs; stale answers cannot authorize another call.
- Child permission inheritance is a trust-model change: discuss and update
  `SECURITY.md` before spawning children with the parent's ask-mode instead
  of `always_allow`.
- Pause/resume keybindings in the TUI (harness already has the commands).

### Coding agent

- Configurable tool allowlist / denylist (today: approvals only, no way to
  disable a tool from config).
- Repository-structure context for the model (a token-budgeted repo map).
  No AST layer exists; earlier versions of this file described one that was
  never merged.

### Harness

- A concrete telemetry exporter (JSONL or OTel). There is no telemetry
  add-on in the tree today.

### Server

- Responding to `ask_user` on a running run (needed before enabling that tool
  by default).
- Authentication (currently expected from a reverse proxy).
- Publishing `core-server` to PyPI.

### New consumers

- Browser-use agent on the same harness.

---

## 5. Non-goals (near term)

- Full IDE / LSP integration.
- Remote sandbox / container isolation for `bash`.
- Replacing the harness control plane with a UI-only event bus, an add-on,
  or three separate packages. Keep one `ControlPlane` with three jobs.
- A plugin loader or durable memory system in 0.1.0.
- Perfect ripgrep parity in `search` (Python search is enough for v1).

---

## 6. How to use this doc

1. Pick an item from the open backlog.
2. Prefer a focused PR (tools ≠ TUI ≠ harness).
3. When work merges, move the fact into "Current state" and delete it from
   the backlog. Do not leave checked boxes describing things that are not in
   the tree.
