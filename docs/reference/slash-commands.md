# Slash commands

Type `/` in the Symphony Code composer to discover commands. Select a suggestion with Tab or Enter. Commands not relevant to your current session or provider may not be available.

| Command | Action |
| --- | --- |
| `/model [id]` | List configured models or switch the active model |
| `/provider [name]` | Add or switch provider credentials |
| `/mode [mode]` | Show or switch the current mode |
| `/plan` | Enter plan mode |
| `/plans [plan]` | Choose and open a workspace plan |
| `/effort [level]` | Set model reasoning effort when supported |
| `/personality [id]` | Choose a prompt personality |
| `/jev [on\|off\|rule]` | Configure the optional completion check |
| `/langfuse` | Configure optional Langfuse tracing |
| `/voice` | Start voice input; available when voice support is configured |
| `/installed` | View installed skills and plugins |
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

The installed command and TUI keyboard controls are documented in the [CLI reference](./cli.md) and [TUI guide](../user-guide/tui.md).
