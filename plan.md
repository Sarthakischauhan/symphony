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

- Usage + context metrics on the control plane
- Context management (warn, compaction, estimates)
- Control-plane product surface (typed events, fan-out, persistence, pause/cancel/inject)
- Multi-turn OpenAI tool-call forwarding

### In flight / parallel — modular coding tools (separate PR)

Split filesystem/shell tools into one module each on a shared `WorkspaceTool` base:

| Tool | Purpose |
|---|---|
| `read_file` | Read UTF-8 text |
| `write_file` | Create / overwrite text |
| `bash` | Shell in workspace |
| `grep` | Regex search (path / glob) |

See PR: modular workspace tools.

### Done this PR — minimal Textual TUI scaffold

- `coding_agent.tui` package with Textual app
- Transcript log + input + status line
- `TextualControlPlane` bridges harness events into the UI
- Entry points: `python -m coding_agent.tui` and `coding-agent-tui`
- Smoke tests without a live API key

### Not started yet

- Streaming token deltas in the TUI
- Edit / apply-patch tools
- Permission / approval gates
- Session resume
- Cancel/pause from the TUI via inbound CP commands

---

## 3. Design Principles

1. **One tool per file** (tools PR) — same `WorkspaceTool` shape everywhere.
2. **Harness stays product-agnostic** — coding-agent specifics stay in `coding_agent`.
3. **Workspace sandbox** — FS tools resolve under a root; escapes raise.
4. **Control plane for UX** — TUI subscribes to CP events; does not scrape stdout.
5. **Tests without keys first** — unit/smoke tests; live API tests stay opt-in.

---

## 4. Implementation Phases

### Phase 1 — Modular coding tools (parallel PR)

- [ ] Split `read_file`, `write_file`, `bash`, `grep` into separate modules
- [ ] Shared `WorkspaceTool` base + `build_tools()`
- [ ] System prompt + unit tests for tools
- [ ] README documents the add-a-tool pattern

### Phase 2 — Minimal Textual TUI ✅ (this PR)

- [x] Add `textual` dependency
- [x] Minimal app: transcript log + input + status
- [x] Control-plane bridge for tool / run events
- [x] Entry points: `python -m coding_agent.tui`, `coding-agent-tui`
- [x] Smoke tests (compose without API key; CP posts messages)
- [ ] Streaming `text_delta` into the log (next polish)
- [ ] Cancel / pause bindings wired to inbound CP commands

### Phase 3 — Agent hardening

- [ ] `edit_file` / patch tool (surgical edits vs full rewrite)
- [ ] Tool result truncation + size caps
- [ ] Permission policy (confirm before bash / overwrite)
- [ ] Configurable tool allowlist / denylist

### Phase 4 — Product UX

- [ ] Live streaming transcript in TUI
- [ ] Collapsible tool-call panels
- [ ] Cancel / pause from UI
- [ ] Session save / resume
- [ ] Usage / context footer from CP `usage` + `context`

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

## 5. Concrete Checklist (next)

### After tools PR merges

- [ ] Rebase TUI onto modular tools (`read_file` / `write_file` / `grep` names in prompt + docs)
- [ ] Show tool names consistently in the TUI log

### TUI polish

- [ ] Buffer/stream `text_delta` without duplicating final `output_text`
- [ ] Disable input while busy (done) + visible spinner / status
- [ ] `--model` / `--workspace` flags documented in root README
- [ ] Optional theme / CSS pass (keep minimal)

### Agent

- [ ] Land Phase 1 tools if not merged
- [ ] Start Phase 3 `edit_file` design note

---

## 6. Non-Goals (near term)

- Full IDE / LSP integration
- Remote sandbox / container isolation
- Replacing the harness control plane with a UI-only event bus
- Perfect ripgrep parity in `grep`

---

## 7. How to Use This Doc

1. Prefer focused PRs (tools ≠ TUI ≠ harness).
2. Update **Current State** and phase checkboxes when work merges.
3. Add backlog rows under Phase 5 instead of rewriting history.

**Primary near-term objectives:** merge Phase 1 tools, then TUI streaming + Phase 3 edit tool.
