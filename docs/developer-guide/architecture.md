# Architecture

Symphony separates provider mechanics, the reusable agent loop, and products built on the loop. Keep product assumptions out of the harness so other agents and interfaces can reuse it.

## Package boundaries

```text
core_ai ──► core_harness ──► coding_agent
                         ├──► core_server
                         └──► browser_agent

All three consumers depend on both core packages.
```

- **`core_ai`** maps provider APIs to shared model, message, and stream types.
- **`core_harness`** owns agent turns, tool dispatch, run limits, cancellation, add-on hooks, and typed events. It does not know about files, terminals, or product session layouts.
- **`coding_agent`** supplies workspace tools, approvals, sessions, learning, and the terminal interface. It is a consumer of the harness, not the harness itself.
- **`browser_agent`** supplies browser-specific tools and a browser session.
- **`core_server`** exposes harness runs and events over HTTP/SSE.

The current checkout is a uv workspace; package purposes and guides are listed in the [docs index](../README.md#build-with-the-harness).

## What happens during a run

1. A product creates a harness with a registry, model id, tools, sink, and optional add-ons.
2. The harness sends the conversation to the selected provider and streams normalized events.
3. When the model requests a tool, the harness invokes registered add-on hooks and executes the callable.
4. The result joins the conversation; the loop continues until the model finishes or a run limit, cancellation, or failure ends it.
5. The harness emits terminal events. Products decide how to display, persist, or forward them.

A product can extend the loop through [add-on hooks](./extending.md). Event names and payloads are described in the [event overview](./events.md) and [full schema catalog](../../core_harness/docs/events.md).

## Design constraints

- **Providers stay replaceable:** products consume shared message and stream contracts, not vendor response objects.
- **Tools are explicit capabilities:** a harness only receives tools its caller registers. It does not provide a sandbox or automatic approval layer.
- **Events are the interface for observers:** UIs and servers consume the stream instead of scraping console output.
- **Products own product behavior:** approvals, files, sessions, and user interaction belong in consumers/add-ons, not the generic loop.

## Explore the implementation

- [Harness API guide](../packages/symphony-harness.md)
- [Add-on lifecycle](./extending.md)
- [TUI implementation architecture](../../coding_agent/TUI_ARCHITECTURE.md)
- [TUI performance investigation](./tui-performance.md)
- [Contributing and test commands](../../AGENTS.md)
