# Learning and memory

Symphony Code can retain selected lessons between tasks, then use relevant memory as context in later runs. Learning is optional agent behavior; it is not part of the generic harness or a source of trusted instructions.

## What to expect

The learning add-on can capture run evidence, prepare and consolidate candidate lessons, and retrieve relevant memory for a later task. Stored material is model-generated reference data: check it when it matters and do not treat it as policy. Memory scopes and settings are controlled by the coding agent configuration.

The `/learning` command opens the learning interface. Use it to inspect available lessons rather than assuming every past conversation is automatically searched or replayed.

## Privacy and controls

Learning data may summarize project work or preferences. Review storage before sharing a machine or workspace. See [Sessions](./sessions.md) for conversation archive privacy and [Security](../../SECURITY.md) for the memory trust boundary.

## Implementation details

The [learning-flow guide](../developer-guide/learning-flow.md) describes capture, consolidation, scopes, retrieval, and implementation ownership for developers. For other persistent context behavior, see [configuration](./configuration.md).
