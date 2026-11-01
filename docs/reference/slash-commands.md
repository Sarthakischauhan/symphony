# Slash commands

Type `/` in the Symphony Code composer to discover commands. Select a suggestion with Tab or Enter. Commands not relevant to your current session or provider may not be available.

| Command | Action |
| --- | --- |
| `/model [id]` | List configured models or switch the active model |
| `/provider [name]` | Add or switch provider credentials |
| `/effort [level]` | Set model reasoning effort when supported |
| `/personality [id]` | Choose a prompt personality |
| `/jev [on\|off\|rule]` | Configure the optional completion check |
| `/langfuse` | Configure optional Langfuse tracing |
| `/voice` | Start voice input; available when voice support is configured |
| `/installed` | View installed skills (state and token cost) and plugins (enabled state, skipped parts, notices) |
| `/skills [command]` | `list` (default), `add <source>`, `remove`, `enable`, `disable`, `mode <name> on\|name-only\|manual\|default`, `update [name]`; with no argument opens the installed screen |
| `/plugins [command]` | `list` (default), `add <source>`, `remove`, `enable`, `disable`, `update [name]`, `marketplace add\|list\|update\|remove`; with no argument opens the installed screen |
| `/compact` | Summarize older conversation context |
| `/context` | Inspect context usage |
| `/status` | Show session and model information |
| `/session` | Inspect session images, compactions, memory, and recorded events |
| `/learning` | Browse curated memory topics and pending captures |
| `/dashboard` | Show active Symphony agents |
| `/diff` | Inspect the workspace diff |
| `/new` | Start a fresh conversation |
| `/reload` | Reload provider environment, registry and user addons ([guide](../addons/README.md)) |
| `/addons` | List loaded and failed user addons |
| `/clear` | Clear the visible transcript |
| `/help` | Show available commands |
| `/quit` | Exit the application (`/exit` also works) |

`/skills` and `/plugins` take the same arguments as `symphony skills` and `symphony plugins` and reload the running session after a change (they are unavailable while a turn is running). The installed command and TUI keyboard controls are documented in the [CLI reference](./cli.md) and [TUI guide](../user-guide/tui.md).
