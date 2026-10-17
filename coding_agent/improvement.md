# Retired developer-preview proposal

This former proposal for TUI caching, gated plan mode, and memory is obsolete
and is not an implementation backlog. Do not implement its former planning
state machine, plan tools, modal approval flow, or tool restrictions.

Plan mode has been removed entirely. There is no replacement planning gate;
normal tool approval policies remain in effect. Legacy plan-mode sessions
must not silently resume with write-capable tools.

For the current implementation and future work, use:

- [TUI architecture](TUI_ARCHITECTURE.md)
- [Learning pipeline](../docs/developer-guide/learning-flow.md)
- [Security policy](../SECURITY.md)
- [Maintainer status and open backlog](../plan.md)
