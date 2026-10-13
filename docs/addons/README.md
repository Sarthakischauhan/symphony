# User addons

A user addon is a small Python folder that adds tools, slash commands and
event handlers to Symphony without changing Symphony itself.

## Where they live

Only `~/.symphony/addons/<name>/` is scanned (`$SYMPHONY_HOME/addons/` when
`SYMPHONY_HOME` is set). There is no project-local addon folder.

Built-in addons are part of Symphony and always load. A user addon cannot
replace one: an addon, tool or command that reuses a built-in name is
skipped and a notice explains why.

## Layout

```
~/.symphony/addons/example/
  addon.toml   # optional
  addon.py
```

`addon.toml` keys (all optional):

| key | default | meaning |
| --- | --- | --- |
| `name` | folder name | addon name |
| `version` | `0.0.0` | shown by `/addons` |
| `entry` | `addon.py` | module file, relative, inside the folder |
| `factory` | `setup` | function called with the API |

Without `addon.toml`, the folder needs an `addon.py` with `setup`. The entry
must stay inside the folder: absolute paths, `..` and symlinks that leave the
folder are rejected.

## The API

```python
from core_harness import Tool
from core_harness.extensions import CommandSpec, ExtensionAPI

def setup(api: ExtensionAPI) -> None:
    api.register_tool(Tool(my_function, name="my_tool"))
    api.register_command(CommandSpec("hi", "Say hi", lambda argument: "hi"))
    unsubscribe = api.on("turn_completed", lambda event, payload: None)

def dispose() -> None:  # optional, called before a reload replaces the addon
    ...
```

- `register_tool` takes a `core_harness.Tool`.
- `register_command` takes a `CommandSpec`; the handler gets the text after
  `/name` and returns the reply (it may be async).
- `on(event, handler)` subscribes to a harness event (`run_started`,
  `turn_completed`, `tool_execution_completed`, ...; see
  `core_harness.extensions.ADDON_EVENTS`). It returns an unsubscribe callable.
  Handlers run inline and must return quickly.

A complete example is in [`docs/addons/example`](example/).

## Reloading

Edit the addon, then run `/reload`. Symphony builds the new addon set, calls
`dispose()` on the old one, and swaps them. If a run is active, the reload
waits for it to end. The notice says `tools changed (+N/-M): prompt cache
will rebuild` when the tool list changed, or `no tool changes`.

## Errors

An addon that fails to import, raises in `setup`, or raises in `dispose` is
skipped. A handler that raises fails only that call. None of these stop the
TUI or the run. `/addons` lists loaded addons (version, tools, commands) and
failed ones (phase and error).
