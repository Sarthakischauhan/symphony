# Extend the harness

Use an `Addon` when product behavior needs to observe or influence a harness run without adding product-specific dependencies to `core_harness`. Add-ons are invoked at run, turn, tool, and compaction boundaries.

## Add an add-on

Subclass `core_harness.addons.Addon` and override only the hooks you need:

| Hook | Runs when | Typical use |
| --- | --- | --- |
| `before_run` / `after_run` | A run starts or ends | Initialize run state or record the result |
| `before_turn` / `after_turn` | A model/tool turn starts or ends | Inject context or observe model activity |
| `before_tool` | Before a registered tool executes | Enforce product policy; return a deny reason to block a call |
| `on_tool` / `on_compact` | A tool or compaction finishes | Record product-side outcomes |
| `fork_for_child` | A child harness is created | Return a child add-on to inherit behavior, or `None` to skip it |

Check the `Addon` class and existing product add-ons for exact hook signatures; do not assume hook payloads beyond what the source defines.

## Keep ownership clear

- The harness invokes hooks but does not decide which product features should be installed.
- Products register add-ons when building their harness. A child may inherit, omit, or receive a replacement set of add-ons.
- Approval behavior is a coding-agent add-on, not a security boundary provided by the generic harness.
- Events needed by every consumer belong in the harness event contract; product-only display state should remain product-specific.

The canonical product example is [`LearningAddon`](../../coding_agent/src/coding_agent/addons/learning/). The coding agent also includes Langfuse and Jev integrations; see the [architecture guide](./architecture.md) for package ownership.

## Verify an extension

1. Test the hook directly, including denial and exceptions where relevant.
2. Test child behavior explicitly if the extension is inherited by spawned agents.
3. Confirm the harness remains independent of product modules.
4. Update the [event overview](./events.md) and [full event catalog](../../core_harness/docs/events.md) if the public event contract changes.

See [contributor conventions](../../AGENTS.md) for test and dependency rules.
