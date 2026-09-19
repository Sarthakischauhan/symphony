# Extending the harness

`CoreHarness` is an extension surface. Product behavior attaches as an
`Addon` and is notified through `notify_addons`. There is no second
control plane.

## Hooks

Override the no-op methods on `Addon`. Signatures stay on that class:

| Hook | Role |
| --- | --- |
| `before_run` / `after_run` | Observe a `CoreHarness.run` |
| `before_turn` / `after_turn` | Observe each model/tool turn |
| `before_tool` | May return a deny reason; otherwise allow |
| `on_tool` / `on_compact` | Record a finished tool or compaction |

`CoreHarness.run` is the other public seam. It returns `HarnessResult`
(`output_text`, `messages`, `tool_calls`, `usage`, context fields).

## `fork_for_child`: inherit vs skip

`fork_for_child` is the inherit path onto a child harness. Return a new
instance to inherit, or `None` (the default) to skip. When
`ChildConfig.addons` or `addon_factory` is set, that list **replaces**
forks.

| Add-on | Policy |
| --- | --- |
| `LangfuseAddon` | **Inherit** — child runs get their own tracer |
| `LearningAddon` | **Skip** — children do not observe or record learning |
| `JevAddon` | **Skip** — children are not evaluated |

`coding_agent.default_addons` mounts Learning when a `LearningLoop` is
passed. The spawn `addon_factory` omits it, matching skip.

## Canonical example: Learning

Learning is observe/record only. `coding_agent` owns `LearningConfig`
and registers `LearningAddon` in `default_addons`. The harness does not
import learning. Learning does not import `core_harness.loop` or
`turn_runner`.

```python
from core_harness.addons import Addon

class LearningAddon(Addon):
    name = "learning"

    def fork_for_child(self, parent_harness):
        return None  # skip

    async def before_run(self, **payload):
        self.loop.cancel()

    async def before_turn(self, **payload):
        # inject memory into the current system message
        ...

    async def after_run(self, **payload):
        self.loop.schedule(payload["task"], payload["result"], emit=payload.get("emit"))
```

`LangfuseAddon` and `JevAddon` are siblings on the same hook surface
(inherit vs skip as in the table). Do not add harness events, badges, or
TUI chrome to extend this path.
