# Architecture

Symphony is the harness. Agents are separate consumers that plug into it.

Keep the harness product-agnostic, keep the provider layer swappable, and
drive every UI from a single control-plane event stream instead of scraping
output. Parent runs can spawn child agents; those children reuse the same
stream, tagged with `parent_id` and `agent_id`.

## Layers

| Layer | Package | Role |
| --- | --- | --- |
| Harness | `symphony-harness` | Turns, tools, control-plane events, compaction |
| Harness | `symphony-core` | OpenAI, Anthropic, Gemini, Grok; catalog; streaming types |
| Agent | `symphony-code` | Workspace tools, JSONL sessions, Textual TUI |
| Server | `core-server` | FastAPI wrapper that streams those events over SSE |

```mermaid
flowchart TD
    subgraph SYM["SYMPHONY · the harness"]
        direction TB
        U["user message"] --> M["model (stream)"]
        M --> TC["tool calls"]
        TC --> CP["control plane"]
        CP --> RT["authorize + run tools"]
        RT --> M
        TC --> FR["final reply"]
        CP --> CTX["context mgmt"]
        CP --> PER["persistence"]
    end

    AI["core_ai · providers"] --> M

    subgraph COD["coding_agent"]
        WS["workspace tools"]
        TU["Textual TUI"]
        SQ["JSONL sessions"]
    end

    subgraph SRV["core_server"]
        API["FastAPI"]
        SSE["SSE event stream"]
    end

    subgraph BROW["browser agent · next"]
        BT["browser tools"]
        BU["browser UX"]
    end

    COD -- "plugs into" --> SYM
    SRV -- "plugs into" --> SYM
    BROW -. "plugs into" .-> SYM
```

## A turn

A turn is `CodingAgent.run` → `CoreHarness.run` → `TurnRunner` →
`ModelRegistry.stream` → `WorkspaceTool.execute`. No façade objects in
between.

## Source layout

```text
core_ai/src/core_ai/
  content.py          # multimodal parts
  types.py            # Message, StreamEvent
  registry.py         # provider:model routing
  models/             # generated catalog snapshot (scripts/generate_models.py owns generated.py)
  providers/
    base.py           # BaseProvider contract
    openai.py         # chat + responses + images
    anthropic.py
    gemini.py
    grok.py
    http.py           # SSE + 429 / SSL MAC / hard-error retry
    catalog.py        # provider catalog helpers
    defaults.py       # credential-aware default registry

core_harness/src/core_harness/
  harness.py          # CoreHarness: tools, limits, run loop, attach add-ons, spawn
  tools.py            # Tool adapter
  events.py           # control planes (Null, Interactive, Fanout, Persisting, Identified)
  models.py           # ControlPlaneEventType, ControlCommand, ToolCall, HarnessResult
  config.py           # HarnessConfig, load_harness_config
  errors.py           # HarnessCancelled, HarnessLimitExceeded
  context/            # token estimates, pruning, HarnessState, keep/drop planner
  loop/               # TurnRunner, tool calls, run session, stream handling
  addons/             # Addon base, persistence, compaction, telemetry, subagent

coding_agent/src/coding_agent/
  agent.py            # CodingAgent + default_addons
  config.py           # .symphony/config.json model
  credentials.py      # ~/.symphony/.env handling
  prompts.py          # system + plan-mode prompts
  plan.py             # plan mode (.symphony/plans/)
  tools/              # one file per workspace tool
  compaction/         # AiCompactionAddon + InferenceCompactor
  learning/           # after-run reflection, lesson store, run_summary
  persistence/        # JSONL sessions
  tui/                # Textual app, driven by CP events

core_server/src/core_server/
  app.py              # FastAPI app, /runs, /models, /health
  sse.py              # SSE control plane
  config.py           # ServerConfig / build_config
  request_limits.py   # body / message / history caps
```

Each package is a small set of modules, one concept per file. Leaf packages of
20-line files are avoided.

## Design principles

1. One tool per file. Same shape everywhere (`WorkspaceTool` + `run` + register).
2. Harness stays product-agnostic. Coding-agent specifics live in `coding_agent`.
3. Workspace root, not a sandbox. File tools resolve paths under the workspace
   root and reject escapes. `bash` runs with the user's permissions behind an
   approval prompt; there is no container or OS-level isolation.
4. Control plane for UX. UIs subscribe to CP events; they do not scrape stdout.
5. Tests without keys first. Unit-test tools and harness; keep live tests opt-in.

## What's next

A browser-use agent is the next consumer of the same harness. See
[`plan.md`](../../plan.md) for what exists today and the open backlog.

## Development

```sh
uv sync
uv run pytest
uv run --package symphony-code symphony
```
