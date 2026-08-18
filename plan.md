# Symphony Plan

Living roadmap for the Symphony monorepo (`core_ai` → `core_harness` → `coding_agent`).

---

## 1. Goal

Ship a reusable agent stack:

| Layer | Package | Role |
|---|---|---|
| Models | `core_ai` | Provider registry + streaming messages |
| Loop | `core_harness` | Multi-turn tool loop + control plane |
| Product | `coding_agent` | Workspace coding agent (tools + UX) |

---

## 2. Current State

### Done (harness / control plane)

Earlier phases for the general-purpose harness are landed:

- Usage + context metrics on the control plane (`usage`, `context`, turn events)
- Context management (warn threshold, compaction, token estimates)
- Control-plane product surface (typed events, fan-out, persistence, inbound pause/cancel/inject)
- Multi-turn OpenAI tool-call forwarding
- Tool result protocol: every tool call gets `success`, `error`, `timeout`, or `cancelled`
- Cancellation stops in-flight model streams and tool execution, then emits and persists `run_cancelled`
- Optional run limits for turns, tool calls, runtime, and tokens (`run_limit_exceeded`)
- Event identity on every control-plane event: `run_id`, `session_id`, `seq`, `ts`, `schema_version`

### Done (coding agent)

`coding_agent` tools use one module each under a shared `WorkspaceTool` base:

| Tool | Module | Purpose |
|---|---|---|
| `read_file` | `tools/read_file.py` | Read UTF-8 text |
| `write_file` | `tools/write_file.py` | Create / overwrite text |
| `patch` | `tools/patch.py` | Surgical exact-text edit |
| `bash` | `tools/bash.py` | Async shell in workspace (streamed, capped, timed out) |
| `search` | `tools/search.py` | File name / content search |
| `ask_user` | `tools/ask_user.py` | Clarifying questions |

- Approval gates ask before bash, file overwrite, or a broad patch (allow once / deny)
- TUI Escape / Ctrl+X sends the harness cancel command and restores the composer
- Safer defaults: 24 turns, 40 tool calls, 10 minutes, 200k tokens
- Learning is enabled by default, capped at 900 output tokens, and pending reflection is cancelled on TUI exit
- `@file` composer search reuses the existing model/command selector

Shared `WorkspaceTool` base handles workspace binding, path escape rejection, pydantic schemas, and `as_harness_tool()`.

### Done (AST semantic layer + self-learning — this PR)

- AST parser emits decorators, constants, call sites, qualified names
- Semantic index: symbols, inheritance, callers/callees; rendered into prompt + `ast_query`
- Post-task learning loop writes `<workspace>/.symphony/learning/{lessons.jsonl,playbook.md}`
- Playbook injected into later system prompts (disable with `enable_learning=False`)

### Follow-up hardening (PR on `feature/agent-tools-followup`)

- [x] Patch whitespace preserved via harness-validated `PatchArgs`
- [x] `RepositoryContextProvider` with hash/mtime cache + token-budgeted repo map
- [x] On-demand `ast_query`; invalidate after edits; pluggable indexer protocol
- [x] Learning: optional LLM reviewer (`should_persist`); proposed vs trusted stores
- [x] Reviewer must read full lesson before propose_update; no in-place trusted rewrites
- [x] Sanitize/redact; atomic JSONL/playbook; learning failures don't fail the agent run

### Not started yet / next

- Pause / resume bindings in the TUI
- Richer lesson synthesis (model-authored summaries)
- Multi-language AST beyond Python

---

## 3. Design Principles

1. **One tool per file.** Same shape everywhere (`WorkspaceTool` + `run` + register).
2. **Harness stays product-agnostic.** Coding-agent specifics live in `coding_agent`.
3. **Workspace sandbox.** All FS tools resolve under a root; escapes raise.
4. **Control plane for UX.** UIs subscribe to CP events; do not scrape stdout.
5. **Tests without keys first.** Unit-test tools and harness; keep live tests opt-in.

---

## 4. Implementation Phases

### Phase 1 — Modular coding tools ✅

- [x] Split `read_file`, `write_file`, `bash`, `grep` into separate modules
- [x] Shared `WorkspaceTool` base + `build_tools()`
- [x] System prompt updated for four tools
- [x] Unit tests for tools (path safety, grep, bash, schemas)
- [x] README documents the add-a-tool pattern

### Phase 2 — Minimal Textual TUI (parallel PR #4)

Scaffold a basic terminal UI so humans can chat with the agent:

- [x] Add `textual` dependency
- [x] Minimal app: transcript log + input box + run agent turn
- [x] Subscribe to control-plane events (tool start/complete; streaming later)
- [x] Entry points: `python -m coding_agent.tui` / `coding-agent-tui`
- [x] Stream `text_delta` into the log without duplicating final output
- [x] Cancel bindings via inbound CP commands

### Phase 3 — Agent hardening ✅ (this PR)

- [x] `patch` / edit-file tool (surgical exact-text edits)
- [x] Expand AST layer: semantic symbols, inheritance, call graph, `ast_query`
- [x] Self-learning loop after each task under `.symphony/learning`
- [x] Permission policy (e.g. confirm before `bash` / overwrite)
- [ ] Configurable tool allowlist / denylist
- [ ] Model-authored lesson summaries (beyond heuristic tips)

### Phase 4 — Product UX

- [x] Streaming transcript in TUI (token deltas)
- [x] Tool-call panels (name, args, result collapse)
- [x] Cancel via inbound control-plane commands
- [x] Session save / resume (messages + workspace path)
- [x] Usage / context footer from CP `usage` + `context` events

### Phase 5 — Platform backlog

| Feature | Why | Depends on |
|---|---|---|
| Middleware hooks | pre/post model & tool | harness lifecycle |
| Parallel tool execution | latency | tool executor + CP ordering |
| Sub-agents / nested harness | orchestration | `run_id` / `parent_run_id` |
| Eval / trace export | JSONL or OTel | event catalog |
| Budget caps | stop on tokens / $ | usage events — token/turn/runtime/tool-call caps landed |
| Multi-provider polish | Anthropic / others | `core_ai` providers |

---

## 5. Concrete Checklist (post-merge)

### Align tools + TUI

- [ ] Merge tools PR and TUI PR (#4); resolve `plan.md` if needed
- [ ] Point TUI docs at `read_file` / `write_file` / `grep` names
- [ ] Stream `text_delta` in TUI without duplicating `output_text`

### Next agent work

- [x] Land `patch` / edit-file tool
- [x] Semantic AST + `ast_query`
- [x] `.symphony` self-learning loop
- [x] Tool result size caps (beyond read/grep)
- [x] Optional permission gate for bash / overwrite

---

## 6. Non-Goals (near term)

- Full IDE / LSP integration
- Remote sandbox / container isolation (local workspace root only for now)
- Replacing `core_harness` control plane with a UI-only event bus
- Perfect ripgrep parity in `grep` (Python search is enough for v1)

---

## 7. Core Harness Refactor: Decongest `harness.py`

### Goal

Keep `CoreHarness` as the public façade and run-loop coordinator, while moving
domain logic into small, testable modules. Preserve the current public API and
observable behavior, especially control-plane event ordering, usage/context
accounting, persistence checkpoints, cancellation, and multi-tool sequencing.

### Responsibilities to separate

`CoreHarness.run()` currently owns session loading, lifecycle orchestration,
stream parsing, usage estimation, context management, inbound commands, tool
registration/execution, message serialization, and all terminal-state
persistence. These are the seams for the refactor.

### Target boundaries

| Target | Responsibility |
|---|---|
| `core_harness/state/state.py` | `HarnessState`: context policy and valid message transitions |
| `core_harness/turn.py` | `TurnRunner`: streamed provider events, usage/context events, tool-call decoding, and tool execution for one turn |
| `core_harness/run.py` | `HarnessRun`: session setup, turn iteration, commands, persistence, and terminal outcomes |
| `core_harness/harness.py` | Public façade and configuration wiring |

Do not introduce a `ToolManager`; `Tool` remains responsible for schema
generation and invocation, while `HarnessRun` owns the ordered name lookup for
the duration of a run.

### Migration phases

1. **Characterize behavior.** Add focused unit tests for tool argument
   decoding/serialization, stream aggregation, usage fallback, conversation
   initialization, and terminal persistence. Keep the existing end-to-end
   tests as compatibility tests.
2. **Move message transitions into state.** Use `HarnessState` for
   assistant/tool/user/injected message changes, while keeping provider calls
   and event emission in the run lifecycle.
3. **Move turn processing into `TurnRunner`.** Keep the event-driven model
   turn and its control-plane emissions together, including tool execution.
4. **Keep `HarnessRun` focused.** It should coordinate turns, persistence,
   commands, and terminal outcomes without interpreting provider events.
5. **Keep `CoreHarness` thin.** It should configure dependencies, register
   `Tool` instances, create `HarnessRun`, and expose the existing public API.
6. **Verify.** Run the existing suite and preserve event order, persistence
   metadata, cancellation behavior, and the public constructor/run signature.

### Acceptance criteria

- `CoreHarness` remains importable from `core_harness` with its current
  constructor and `run()` signature.
- Existing tests pass without changing event names/order or result values.
- Conversation transitions and the complete run lifecycle have clear owners
  without introducing pass-through helper modules.
- `harness.py` contains orchestration and wiring rather than every concern's
  implementation details.

### Non-goals

- No parallel tool execution, retries, middleware, or new provider behavior.
- No changes to the public `Tool` API, persistence protocol, or event catalog.
- No broad package rename unless needed to avoid import cycles.

---

## 8. How to Use This Doc

1. Pick the next open phase checklist item.
2. Prefer a focused PR (tools ≠ TUI ≠ harness metrics).
3. Update **Current State** and checkboxes when work merges.
4. Add new backlog rows under Phase 5 instead of rewriting history.

**Primary near-term objectives:** richer learning summaries, pause/resume UX, multi-language AST.
