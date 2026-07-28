# Symphony General-Purpose Harness Plan

Planning doc for evolving `core_harness` into a general-purpose agent harness, with the control plane as the primary observability and lifecycle surface. Use this file to scope and sequence new features.

---

## 1. Goal

Ship a reusable harness that any agent product (`coding_agent` and beyond) can sit on top of:

- run a multi-turn model + tools loop
- emit a stable control-plane event stream for UI, logging, evals, and planning
- track **tokens used** and **context left** every turn
- stay provider-agnostic via `core_ai`

Out of scope for the first control-plane push: product UI, persistence backends, inbound command bus (pause/abort/inject). Those are later phases listed below.

---

## 2. Current State (baseline)

### Packages

| Package | Role today |
|---|---|
| `core_ai` | Provider registry + streaming `Message` / `StreamEvent` |
| `core_harness` | Agent loop + tools + emit-only control plane |
| `coding_agent` | Stub consumer |

### Control plane today

- Protocol: `async emit(event_type: str, payload: dict)`
- Default sink: `NullControlPlane` (in-memory event list)
- Tools can opt into CP via a `control_plane` parameter (stripped from LLM schema)

### Events emitted today

| Event | Payload |
|---|---|
| `run_started` | `model_id`, `tool_names` |
| `text_delta` | `turn`, `delta` |
| `tool_call_started` | `turn`, `tool_call_id`, `tool_name` |
| `tool_execution_started` | `tool_call_id`, `tool_name`, `arguments` |
| `tool_execution_completed` | `tool_call_id`, `tool_name`, `result` |
| `run_completed` | `turn`, `output_text` |

### Gaps this plan closes first

- no usage / token metrics anywhere (`core_ai` or harness)
- no context-window / context-left accounting
- no turn-level or usage control-plane events
- stream `done` / `text_start` unused by harness
- no typed event catalog (stringly + free-form dict)
- no failure / max-turns / cancel events
- OpenAI provider does not request or forward usage chunks
- OpenAI provider does not forward assistant `tool_calls` on subsequent turns (multi-turn bug)

---

## 3. Design Principles

1. **Harness owns the control plane.** Providers emit stream events; harness translates lifecycle + metrics into CP emits.
2. **Keep `emit(event_type, payload)`.** Extend payloads and event names; do not break the Protocol for v1.
3. **Metrics ride the side channel first.** Prefer CP events (`usage`, `context`) before bloating `HarnessResult`; then mirror summaries onto the result once stable.
4. **Provider → stream → harness → CP.** Usage enters as a new stream event (or `done` payload), harness aggregates and emits.
5. **NullControlPlane stays the test sink.** Assert ordered `event_types` + payload fields.
6. **General-purpose, not coding-agent-specific.** No product assumptions in `core_harness`.

---

## 4. Control Plane Push — Events, Tokens, Context

### 4.1 Event catalog (target)

Keep existing events. Add:

| Event | When | Payload (minimum) |
|---|---|---|
| `turn_started` | start of each harness turn | `turn`, `message_count` |
| `turn_completed` | end of each model stream (before tool exec or run end) | `turn`, `had_tool_calls` |
| `tool_call_delta` | optional; stream tool arg chunks to CP | `turn`, `tool_call_id`, `delta` |
| `usage` | after each provider stream that reports usage | `turn`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cumulative_tokens` |
| `context` | after each turn once budget is known | `turn`, `context_limit`, `tokens_used`, `context_left`, `utilization` |
| `run_failed` | uncaught error or max turns exceeded | `turn`, `error_type`, `message` |
| `run_completed` | extend existing | add `usage` summary + final `context` snapshot |

Optional later (not required for first PR):

- `run_cancelled`
- `compaction_started` / `compaction_completed` (when context management lands)
- typed pydantic event union / discriminated events

### 4.2 Tokens used

**Source of truth:** provider stream usage.

Work in `core_ai`:

1. Extend `StreamEvent` (or add sibling) to carry usage, e.g.:
   - `type: "usage"` with `prompt_tokens`, `completion_tokens`, `total_tokens`
   - and/or attach usage onto `done`
2. OpenAI provider:
   - set `stream_options: {"include_usage": true}`
   - parse final chunk where `choices` may be empty but `usage` is present (today those chunks are skipped)
3. Keep registry as a passthrough; no aggregation there.

Work in `core_harness`:

1. On usage stream event, accumulate per-run totals.
2. Emit CP `usage` each turn with turn + cumulative fields.
3. Include cumulative usage on `run_completed` (and eventually on `HarnessResult`).

Model config (needed for context left):

- introduce a small model metadata map (limit tokens / context window) keyed by `model_id` or model name
- start with a static table + override hook; do not hardcode only OpenAI

### 4.3 Context left

Definition for v1:

```
context_left = context_limit - tokens_used_for_budget
```

Where `tokens_used_for_budget` is preferably **prompt tokens of the next/current turn** (what occupies the window), falling back to cumulative total if only that is available.

Emit CP `context` after each turn:

```json
{
  "turn": 0,
  "context_limit": 128000,
  "tokens_used": 4200,
  "context_left": 123800,
  "utilization": 0.033
}
```

Rules:

- if `context_limit` unknown → emit `context` with `context_limit: null`, `context_left: null`, still report `tokens_used`
- never block the run solely because context metadata is missing
- later: warn / compact when `context_left` drops below a threshold (separate feature)

### 4.4 Suggested data shapes

```python
# core_ai — stream usage
class StreamEvent(BaseModel):
    type: Literal[
        "text_start", "text_delta",
        "toolcall_start", "toolcall_delta",
        "usage", "done",
    ]
    # existing fields...
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


# core_harness — run-level usage accumulator (internal)
@dataclass
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# later on HarnessResult
class HarnessResult(BaseModel):
    output_text: str
    messages: List[Message]
    tool_calls: List[ToolCall] = Field(default_factory=list)
    usage: Optional[UsageTotals] = None
    context_limit: Optional[int] = None
    context_left: Optional[int] = None
```

Control plane stays envelope-based:

```python
class ControlPlaneEvent(BaseModel):
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
```

---

## 5. Implementation Phases

### Phase A — Control plane metrics (this feature branch focus)

1. **`core_ai` usage plumbing**
   - stream usage events
   - OpenAI `include_usage` + parse usage chunks
   - unit/fake tests that do not require live API keys
2. **Model context limits**
   - metadata lookup by model id/name
   - override/injection point for custom limits
3. **`core_harness` aggregation + emits**
   - `turn_started` / `turn_completed`
   - `usage` and `context` events
   - extend `run_completed` + `run_failed` (max turns)
   - optional mirror fields on `HarnessResult`
4. **Tests**
   - FakeRegistry yields usage events
   - assert CP sequence includes usage/context
   - assert cumulative totals across multi-turn tool loop
5. **Docs**
   - update `core_harness/README.md` event table
   - keep this `plan.md` as the living roadmap

### Phase B — Harden the loop (prerequisite for real agents)

1. Fix OpenAI multi-turn: forward assistant `tool_calls` in HTTP payload
2. Emit `run_failed` instead of bare raise where useful; still re-raise or return error result (decide)
3. Surface `tool_call_delta` to CP if UIs need progressive tool args
4. Export real APIs from `core_ai.__init__` / keep harness public surface honest

### Phase C — Context management

1. Threshold hooks (`context_left` low → warn event) — done (`context_warning`, `context_warn_threshold`)
2. Compaction / summarization strategy (pluggable) — done (`Compactor`, `KeepSystemRecentCompactor`, `compaction_*` events)
3. Token estimation fallback when provider usage missing (local tokenizer or heuristic) — done (char/4 estimate, `usage.estimated`)
4. Per-message size accounting for planning/debug — done (`context.message_sizes`)

### Phase D — Control plane as product surface

1. Typed event catalog (enum or pydantic discriminated union) — done (`ControlPlaneEventType`, string-compatible)
2. Subscribers / fan-out (multiple sinks: log, metrics, UI websocket) — done (`FanoutControlPlane`, `InteractiveControlPlane` subscribers)
3. Persistence adapter interface (append-only event log) — done (`EventLog`, `InMemoryEventLog`, `PersistingControlPlane`)
4. Inbound commands later: cancel, inject message, pause — done (`ControlCommand`, `send_command` / `drain_commands`, harness `paused`/`run_cancelled`/`message_injected`)

### Phase E — General-purpose harness features (planning backlog)

Use this section when planning new features. Each item should become its own design note or PR.

| Feature | Why | Depends on |
|---|---|---|
| Session / conversation resume | multi-request agents | stable messages + usage on result |
| Streaming result API | UI can consume without custom CP | CP events or async iterator wrapper |
| Middleware hooks | pre/post model, pre/post tool | harness lifecycle |
| Permission / tool policy gate | safe coding agents | tool execution path |
| Parallel tool execution | latency | tool executor + CP ordering rules |
| Sub-agents / nested harness | orchestration | CP correlation ids (`run_id`, `parent_run_id`) |
| Eval / trace export | OpenTelemetry or JSONL traces | event catalog + usage |
| Model fallback / retry | reliability | turn failure events |
| Budget caps | stop when tokens or $ exceed limit | usage events |
| `coding_agent` vertical | first real consumer | Phases A–B |

### Phase F — Correlation & identity

For general-purpose use, every run should carry:

- `run_id` (uuid) on `run_started` and all subsequent events
- `turn` (already present on some events — make consistent)
- optional `parent_run_id` / `session_id`

Add these to all CP payloads once, early — cheap and unblocks tracing.

---

## 6. Concrete Work Checklist (Phase A)

### `core_ai`

- [ ] Add usage fields / `usage` stream event type
- [ ] OpenAI: `stream_options.include_usage = true`
- [ ] OpenAI: handle chunks with `usage` and empty `choices`
- [ ] Do not drop usage when finishing with `done`
- [ ] Tests with recorded/fake SSE chunks
- [ ] Document usage event in `core_ai/README.md`

### `core_harness`

- [ ] Accept optional `context_limit` (or model metadata provider) on `CoreHarness`
- [ ] Accumulate usage across turns
- [ ] Emit `turn_started`, `turn_completed`, `usage`, `context`
- [ ] Extend `run_completed` payload with totals
- [ ] Emit `run_failed` on max-turns (and decide error UX)
- [ ] Optionally add usage/context fields to `HarnessResult`
- [ ] Update `NullControlPlane` tests / event sequence assertions
- [ ] Update README event list + PrintControlPlane example showing usage

### Repo / DX

- [ ] Keep this `plan.md` updated as decisions land
- [ ] No co-authored commit trailers; author = repo owner
- [ ] Feature branch: `feature/control-plane`

---

## 7. Event Sequence (target happy path)

```
run_started
turn_started
  text_delta*
  tool_call_started?
  tool_call_delta*
usage
context
turn_completed
tool_execution_started
tool_execution_completed
turn_started
  text_delta*
usage
context
turn_completed
run_completed   # includes cumulative usage + final context
```

Failure path:

```
run_started
turn_started
...
run_failed      # max_turns or exception
```

---

## 8. Test Plan

1. **Unit (harness):** FakeRegistry yields tool loop + usage events → assert CP order and cumulative tokens / context_left math.
2. **Unit (provider):** Fake SSE lines including a final usage-only chunk → assert `usage` stream event.
3. **Regression:** existing `test_core_harness_runs_tool_loop` updated for new events (insert `turn_*`, `usage`, `context` as implemented).
4. **Live (optional):** OpenAI smoke test asserts usage fields present when `OPENAI_API_KEY` set.

---

## 9. Open Decisions

Record answers here as you plan features:

1. **Budget basis:** Is `context_left` based on last prompt tokens, cumulative total, or estimated next-prompt size?
2. **Missing usage:** Fail soft (nulls) or estimate locally?
3. **`HarnessResult`:** Mirror metrics in v1 or CP-only first?
4. **Max turns:** `run_failed` event + raise, or return error result?
5. **Typed events:** keep strings for now, or introduce enum aliases without breaking Protocol?
6. **Context limit source:** static map in repo vs caller-supplied vs provider capability API?

**Proposed defaults for Phase A:** soft-nulls when unknown; mirror summary on `HarnessResult`; `run_failed` + raise on max turns; string event names; caller override + small static limit map.

---

## 10. Non-Goals (near term)

- Replacing the control plane with OpenTelemetry-only (can export later)
- Full inbound control protocol (cancel/pause) before outbound metrics are solid
- Building `coding_agent` UX in the same PR as metrics plumbing
- Perfect token estimators for every provider on day one

---

## 11. How to Use This Doc

When planning a new feature:

1. Find the phase it belongs to (A–F) or add a row under Phase E.
2. Note which CP events / payloads it needs.
3. List `core_ai` vs `core_harness` vs `coding_agent` touchpoints.
4. Add a checklist under section 6 or a new section.
5. Implement on a focused branch; update this plan when decisions change.

Primary near-term objective: **Phase A — control plane handles events, tokens used, and context left.**
