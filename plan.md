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

### Done (coding agent tools — this phase)

`coding_agent` tools are no longer a single monolith. Each tool is its own module under a clear pattern:

| Tool | Module | Purpose |
|---|---|---|
| `read_file` | `tools/read_file.py` | Read UTF-8 text |
| `write_file` | `tools/write_file.py` | Create / overwrite text |
| `bash` | `tools/bash.py` | Shell in workspace |
| `grep` | `tools/grep.py` | Regex search (path / glob) |

Shared `WorkspaceTool` base handles workspace binding, path escape rejection, and `as_harness_tool()`. New tools: subclass → set `name`/`description` → implement `run` → register in `TOOL_CLASSES`.

Unit tests cover tools without a live API key; the live bubble-sort integration test remains optional.

### Not started yet

- Interactive TUI (Textual)
- CLI entrypoint packaging
- Edit / apply-patch style tools
- Permission / approval gates for destructive tools
- Session resume + richer CP-driven UI

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
- [ ] Stream `text_delta` into the log without duplicating final output
- [ ] Cancel / pause bindings via inbound CP commands

### Phase 3 — Agent hardening

- [ ] `edit_file` / patch tool (surgical edits vs full rewrite)
- [ ] Tool result truncation + size caps for model context
- [ ] Permission policy (e.g. confirm before `bash` / overwrite)
- [ ] Configurable tool allowlist / denylist
- [ ] Richer errors returned as structured strings (already started)

### Phase 4 — Product UX

- [ ] Streaming transcript in TUI (token deltas)
- [ ] Tool-call panels (name, args, result collapse)
- [ ] Cancel / pause via inbound control-plane commands
- [ ] Session save / resume (messages + workspace path)
- [ ] Usage / context footer from CP `usage` + `context` events

### Phase 5 — Platform backlog

| Feature | Why | Depends on |
|---|---|---|
| Middleware hooks | pre/post model & tool | harness lifecycle |
| Parallel tool execution | latency | tool executor + CP ordering |
| Sub-agents / nested harness | orchestration | `run_id` / `parent_run_id` |
| Eval / trace export | JSONL or OTel | event catalog |
| Budget caps | stop on tokens / $ | usage events |
| Multi-provider polish | Anthropic / others | `core_ai` providers |

---

## 5. Concrete Checklist (post-merge)

### Align tools + TUI

- [ ] Merge tools PR and TUI PR (#4); resolve `plan.md` if needed
- [ ] Point TUI docs at `read_file` / `write_file` / `grep` names
- [ ] Stream `text_delta` in TUI without duplicating `output_text`

### Next agent work

- [ ] Design `edit_file` / patch tool
- [ ] Tool result size caps
- [ ] Optional permission gate for bash / overwrite

---

## 6. Non-Goals (near term)

- Full IDE / LSP integration
- Remote sandbox / container isolation (local workspace root only for now)
- Replacing `core_harness` control plane with a UI-only event bus
- Perfect ripgrep parity in `grep` (Python search is enough for v1)

---

## 7. How to Use This Doc

1. Pick the next open phase checklist item.
2. Prefer a focused PR (tools ≠ TUI ≠ harness metrics).
3. Update **Current State** and checkboxes when work merges.
4. Add new backlog rows under Phase 5 instead of rewriting history.

**Primary near-term objectives:** merge this tools PR + TUI PR (#4), then streaming polish and Phase 3 `edit_file`.
