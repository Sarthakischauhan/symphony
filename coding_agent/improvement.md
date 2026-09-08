# Developer preview: TUI cache, plan mode, Hermes memory

Status: proposed implementation. Nothing in this file is shipped until
the matching code, tests, and docs land. Symphony should implement this
document and ship when the acceptance checks pass.

This file **replaces** the previous control-plane / addon ownership plan.
Do not implement that older work from this path.

## Objective

Make the first developer preview of `symphony-code` usable:

1. The TUI stays responsive on long sessions and resume.
2. Plan mode is a real gated planning phase (Grok-like), not a swallowed
   transcript plus a tool-list mutation.
3. Learnings follow Hermes: a small curated `MEMORY.md` the agent writes
   through a `memory` tool, plus a background review that proposes memory
   ops. Not opaque JSONL "historical notes".

Stay inside `coding_agent`. The harness stays product-agnostic. Do not
change child-approval defaults (`SECURITY.md`: children skip
`ApprovalAddon`). Mock providers in tests; never call a live API.

## Conventions

- One tool per file under `coding_agent/src/coding_agent/tools/`, subclass
  `WorkspaceTool`.
- UIs consume control-plane events; they never scrape stdout.
- Prefer product-local events (same pattern as `run_summary`) over new
  `ControlPlaneEventType` values. If you add or rename a harness event,
  update the enum **and** both event docs.
- Docs describe the tree after the change. Update user/developer docs in
  the same PR that ships the behavior.
- `uv run pytest` and `uv run ruff check .` must pass. No new ruff ignores.
- Discuss trust-model changes before merging them; update `SECURITY.md`
  when guarantees change. This work **does** change guarantees: bash is
  allowed in plan mode (not write-scanned), and memory is injected into
  the system prompt.

## Out of scope (do not build)

- Control-plane / authorization-contract rewrite (the previous contents
  of this file).
- Honcho, FTS5 session search, `/learn` from URLs, Skills Hub, journey
  constellation UI, external memory providers.
- Skill-from-experience (`skill_manage`), global `~/.symphony/memory/`,
  write-approval staging UI, `playbook.md` synthesis from `plan.md`.
- Line-range comments on the plan modal.
- Changing child `ApprovalAddon` skip / `always_allow` spawn policy.
- OS sandbox, path jail, or harness-owned plan/memory.

---

## Current bugs (verify before editing)

### Plan mode

| Fact | Where |
| --- | --- |
| Four-bullet prompt | `coding_agent/src/coding_agent/prompts.py` `PLAN_MODE_PROMPT` |
| Mutates `harness.tools` to `{read_file, search}` for the run | `CodingAgent.run()` in `agent.py` |
| TUI `begin()` on submit **and** agent `begin()` on run | `tui/composer/surface.py`, `agent.py` |
| `save()` calls `begin()` again and resets the stream | `plan.py` `PlanStore.save` |
| Plan `text_delta` is appended to the file and **not** presented | `tui/runtime/turn.py` `on_harness_event` |
| Modal "Build now" auto-submits `Build the approved plan in {path}.` | `tui/commands/manager.py` `on_plan_action` |
| `/plan` is a saved-plan picker, not enter-plan-mode | `tui/commands/catalog.py` |
| `ask_user` and `spawn_agent` stripped because tools are mutated | `agent.py` |
| Learning skipped in plan mode | `LearningAddon(should_review=lambda: self.mode != "plan")` |

### Learning

| Fact | Where |
| --- | --- |
| After-run JSON review → `Lesson` JSONL | `learning/loop.py`, `learning/store.py` |
| Injected as "historical notes, never as instructions" | `LearningStore.context_for`, `agent.py` |
| Overlap rank else last 2; cap 200 lessons | `store.py`, `LearningConfig` |
| `/learning` renders JSONL markdown | `store.to_markdown` |
| `plan.md` "Durable memory / playbook.md" backlog | **superseded** by this file |

### TUI speed

| Fact | Where |
| --- | --- |
| Deltas throttled to ~15 fps; stream bodies are plain text | `tui/runtime/turn.py`, `tui/runtime/events.py`, `transcript/process.py` |
| Completed assistant/reasoning switch to `themed_markdown` | `transcript/process.py` `ReasoningWidget.complete`, assistant finish path |
| Resume remounts every conversation message as widgets | `tui/screens/history.py` `load_session_history` |
| Live tool cards capped; older tools fold to Explored/Archived | `transcript/surface.py`, `transcript/archive.py` |
| `@` file search and `/plan` picker recompute on every key | `tui/composer/surface.py` |

---

## Target

### 1. TUI render cache

Keep streaming as plain text. Freeze completed widgets so Markdown is
parsed **once**. Resume from a compact reconstructed view, not a full
replay of every tool card. Cache `@` matches and slash-plan lists for
the session.

Measure (no live API):

- Resume of a recorded long JSONL session: time from `on_mount` to
  `finalize_transcript_history`, and widget count in `#transcript`.
- Presenter driven with a burst of `text_delta` / `tool_call_delta`
  events: no per-delta Markdown parse.

### 2. Plan mode

State machine on the product agent (not the harness):

```
Inactive --> Pending     Tab or /plan while idle
Pending  --> Active      first user prompt of that plan session
Inactive --> Active      enter_plan_mode tool approved
Active   --> Inactive    exit_plan_mode approved, or toggle off while idle
Active   --> ExitPending toggle off while a turn is in flight
ExitPending --> Inactive turn completes
```

Persist only `Active` across resume (session JSONL product event
`plan_mode_changed` is enough). Collapse `Pending` / `ExitPending` to
`Inactive` on restart.

**Gate** via a new `PlanModeAddon.before_tool` (same hook as
`ApprovalAddon`). Do **not** mutate `harness.tools`.

| Allow | Auto-allow (no approval) | Deny with a short reason |
| --- | --- | --- |
| `read_file`, `search`, `ask_user`, `bash`, `memory` | `write_file` / `patch` only when the target path is the current plan file | `spawn_agent`, `generate_image`, any other write |

`spawn_agent` stays denied: children skip `ApprovalAddon` and would
punch through the gate. Bash is allowed for inspection and is **not**
write-scanned (Grok residual). Document that in `SECURITY.md`.

Single `PlanStore` owner: agent/addon initializes the current plan file.
TUI must not call `begin`/`append`. Delete the `text_delta` swallow in
`turn.py` so plan tokens render in the transcript. The plan file is the
source of truth; the agent writes it with `write_file`/`patch`.

Structured `PLAN_MODE_PROMPT`: Context, recommended approach, files to
change, existing functions to reuse, verification, open questions.

`enter_plan_mode` and `exit_plan_mode` are product tools (one file each)
that use `sink.request_user_input` like `ask_user` / `ApprovalAddon`.
`exit_plan_mode` reads the plan from disk and the TUI opens `PlanModal`.

Modal actions:

- **Approve & build** — set mode `build`, start a turn with an explicit
  user message to implement the plan at the relative path.
- **Request changes** — stay `Active`, send the notes as the next user
  message.
- **Quit** — leave plan mode, do not start a build.

No line-range comments.

`/plan` enters plan mode (optional rest of the line is the first prompt).
`/plans` is the saved-plan picker/modal. Tab still toggles. Compaction
`on_compact` injects a reminder that plan mode is still active.

### 3. Hermes-style memory

Workspace files (hard limits, error on overflow — no silent drop):

```
.symphony/memory/MEMORY.md   # ~3000 chars, agent notes
.symphony/memory/USER.md     # ~1500 chars, user preferences
```

Frozen snapshot injected into the system prompt at `CodingAgent`
construction (and `/new` / `/reload`). Mid-session writes hit disk
immediately and return in the tool result; they do not rewrite
`harness.system_prompt` mid-run.

New tool `coding_agent/tools/memory.py`: actions `add` / `replace` /
`remove`, targets `memory` | `user`. Replace/remove use unique substring
match; ambiguous match returns an error. Overflow returns usage + current
entries so the agent consolidates in the same turn. Sanitize with
`learning/sanitize.py` (extend patterns as needed). Duplicate add is a
no-op success.

Background review stays `after_run`, `tools=[]`, non-blocking, skipped
in plan mode and when `learning.enabled` is false. Schema becomes
structured `memory_ops` plus `transcript_summary`. The **host** applies
ops after sanitize. The reviewer never receives `bash` or `write_file`.
Keep the two-line `run_summary` / "summary so far".

`--no-learning` / `learning.enabled=false` hides the memory tool and
skips review. Children do not inherit `LearningAddon` and do not get the
memory tool.

One-shot migrate `.symphony/learning/lessons.jsonl` into `MEMORY.md`
(condensed, sanitized, respect the char limit). Stop injecting JSONL
into the prompt. `/learning` renders `MEMORY.md` and `USER.md`.

Nudge in `SYSTEM_PROMPT`: persist durable facts via `memory`; do not
store task progress or secrets; procedures belong in skills (read
`SKILL.md` when relevant).

---

## Implementation sequence

Ship as four independently mergeable PRs. 1, 2, and 4 can proceed in
parallel. 3 requires 2. Update docs in the PR that ships the behavior.

### PR 1 — TUI render cache

**Title:** Freeze completed transcript widgets and cheapen resume.

**Files:** `tui/transcript/messages.py`, `tui/transcript/process.py`,
`tui/transcript/surface.py`, `tui/transcript/archive.py`,
`tui/screens/history.py`, `tui/composer/surface.py` (picker cache),
`tui/theme/colors.py` (`themed_markdown` call sites), tests in
`coding_agent/tests/test_tui.py`.

**Do:**

1. After an assistant/reasoning/tool body completes, parse Markdown once
   and keep the rendered content. Later refreshes must not re-parse.
2. Completed widgets should not invalidate the whole transcript layout
   when a new delta arrives elsewhere.
3. Resume: mount user/assistant text and a compact tool summary; do not
   expand every historical tool card. Existing Explored/Archived path is
   the model — use it for history too.
4. Cache workspace file matches for `@` and plan-list results until
   `/reload` or a successful write/patch/bash that could change them.
   Simple mtime or "invalidate on those tool completions" is enough.
5. Keep the 15 fps stream paint. Do not Markdown-parse incomplete text.

**Acceptance:**

- A test that finishes an assistant message, then triggers a chrome
  refresh, does not call Markdown parse again (patch/spy
  `themed_markdown` or the widget update path).
- History load of N assistant+tool pairs produces a bounded widget count
  (assert against the live-tool cap / archive), not N tool cards.
- Existing TUI tests still pass. No live API.

### PR 2 — Plan-mode gate and store

**Title:** Gate plan mode in `before_tool`; stop swallowing the transcript.

**Files:** new `coding_agent/src/coding_agent/plan_mode.py` (addon +
state), `plan.py`, `agent.py`, `prompts.py`, `tui/runtime/turn.py`,
`tui/composer/surface.py`, `compaction` `on_compact` reminder,
`tests/test_plan.py`, `SECURITY.md` (bash-in-plan note).

**Do:**

1. `PlanModeAddon.before_tool` implements the allow/auto-allow/deny
   table. Mount it next to `ApprovalAddon`. `fork_for_child` returns
   `None`.
2. Remove `harness.tools` mutation in `CodingAgent.run()`.
3. `PlanStore.begin` is idempotent for the same task. `save()` must not
   call `begin()` (no stream reset). TUI submit must not `begin()`.
4. Delete plan `text_delta` intercept in `turn.py`. Plan tokens go
   through the normal presenter.
5. Rewrite `PLAN_MODE_PROMPT` with the required sections.
6. On compact while Active, add a short reminder that plan mode is on
   and the only writable path is the current plan file.
7. Keep Tab toggle and skip learning while `mode == "plan"`.

**Acceptance:**

- Plan-mode run has the full tool registry on the harness; denied tools
  return a deny reason and never execute (`write_file` on `src/foo.py`
  denied; `write_file` on the current plan path allowed).
- `spawn_agent` denied in plan mode.
- Assistant text appears in the transcript during a plan run (presenter
  sees `text_delta`).
- `PlanStore.save` does not wipe a previously begun file's identity.
- Tests mock the harness/provider.

### PR 3 — Plan approve UX

**Title:** `enter_plan_mode` / `exit_plan_mode` and `/plan` vs `/plans`.

**Depends on:** PR 2.

**Files:** `tools/enter_plan_mode.py`, `tools/exit_plan_mode.py`,
`tools/__init__.py` `TOOL_CLASSES`, `tui/screens/plan.py`,
`tui/commands/catalog.py`, `tui/commands/manager.py`, TUI tests,
`docs/user-guide/tui.md`, `docs/reference/slash-commands.md`.

**Do:**

1. `enter_plan_mode` asks the user (approval kind) then sets Active.
2. `exit_plan_mode` reads the plan file and emits enough for the TUI to
   open `PlanModal` (product event is fine; do not add a harness enum
   value unless you must).
3. Modal: Approve & build / Request changes / Quit as specified.
4. `/plan` enters mode; `/plan <text>` enters and submits. `/plans`
   opens the picker/modal. Update slash catalog strings.
5. Agent-initiated enter is in scope. If the TUI cannot host a second
   nested approval cleanly, enter-from-tool may reuse the existing
   approval composer (`kind="approval"`).

**Acceptance:**

- Approving starts a **build** turn whose user text names the plan path.
- Request changes leaves mode `plan` and sends the notes.
- Quit sets `build` and does not start a run.
- `/plan` no longer means "open picker" unless you keep `/plan` with no
  args as enter-only and `/plans` as picker — do not leave two meanings
  on one command.

### PR 4 — MEMORY.md, memory tool, review migration

**Title:** Replace JSONL lesson injection with Hermes-style memory.

**Files:** `tools/memory.py`, `tools/__init__.py`, `learning/store.py`
(or a new `learning/memory_files.py` — do not keep two sources of
prompt memory), `learning/loop.py`, `learning/prompts.py`,
`learning/addon.py`, `agent.py`, `prompts.py` `SYSTEM_PROMPT`,
`config.py` `LearningConfig` (char limits; drop prompt-injection knobs
that only served JSONL if unused), `/learning` modal,
`tests/test_learning.py`, `docs/user-guide/learning.md`, `SECURITY.md`
(memory is untrusted data in the system prompt; sanitize on write).

**Do:**

1. Bounded markdown files + snapshot helper. Overflow is a tool error.
2. Register `memory` in `TOOL_CLASSES`. Omit it from the schema when
   learning is disabled (filter in `build_tools` / agent construction).
3. Change the reviewer JSON schema to `memory_ops` + `transcript_summary`.
   Host applies ops. Cap ops per review (e.g. 4).
4. Migrate existing `lessons.jsonl` once on store init; leave the file
   as an unused archive (do not delete user data in the first cut).
5. Stop calling `context_for` into the system prompt. Inject the frozen
   snapshot instead.
6. `/learning` shows the two markdown files (empty state if missing).
7. Children: no memory tool, no LearningAddon (already `fork_for_child
   -> None`).

**Acceptance:**

- `memory add` that would exceed the limit fails with usage + entries;
   a follow-up `replace`/`remove` then `add` can succeed.
- Secrets and injection phrases are redacted/neutralized before disk
   and before snapshot inject.
- After migration, a new run's system prompt contains MEMORY.md text
   and does **not** contain the old "Relevant lessons from earlier runs"
   block.
- Reviewer with `should_save` replaced by ops: `should_save` JSON is
   rejected or ignored; tests feed a mock stream.
- `--no-learning` : no memory tool in `harness.tools`, no after_run
   schedule.

---

## Event and prompt notes

- `run_summary` stays a product event. Optional new product events:
  `plan_mode_changed` `{state, plan_path}`, `memory_updated`
  `{target, action}` (TUI may show a one-line notice; default quiet is
  fine).
- Do not add these to `ControlPlaneEventType`. Document them under
  "Product events" in `docs/developer-guide/events.md` when emitted.
- Compaction reminder is prompt/context text, not a new event.

## Trust model (update `SECURITY.md` in the PR that lands the behavior)

- Plan mode allows `bash`. Redirection and in-place writes via the
  shell are not inspected. The gate blocks `write_file` / `patch` /
  `generate_image` / `spawn_agent` only.
- Memory files are model-authored and injected into the system prompt.
  Sanitize on write. Treat them as untrusted data, not instructions
  (keep that wording in the snapshot header).
- Children still skip `ApprovalAddon` and still must not get plan-mode
  or memory addons.

## Validation

Per PR: targeted `uv run pytest coding_agent/tests/...` then full
`uv run pytest` and `uv run ruff check .`.

Do not add tests whose only purpose is this markdown file.

When a PR merges, this document's corresponding section can be marked
done in a follow-up, or deleted once all four PRs are in the tree.
`plan.md` "Durable memory" backlog is superseded; remove or rewrite
that bullet in the PR that lands memory.

## Suggested agent workflow

Implement PR 1 first if the TUI is too slow to work in. Then PR 2, then
PR 3, then PR 4. After each PR: tests, ruff, docs that match the tree.
Ship whenever the four acceptances hold; do not wait for out-of-scope
items.
