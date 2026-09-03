# Slash commands

Type `/` in the composer to discover commands. Tab or Enter selects from the
menu.

| Command | What it does |
| --- | --- |
| `/model [id]` | Show the credential-filtered catalog, or switch model |
| `/mode [mode]` | View or switch **build** / **plan** |
| `/effort [level]` | Set reasoning effort (`none` … `max`) |
| `/plan [plan]` | Searchable picker for saved workspace plans |
| `/provider [name]` | Add or update a provider API key (OpenAI, Anthropic, Gemini) |
| `/new` | Start a fresh persisted session |
| `/reload` | Reload `~/.symphony/.env` (and workspace `.env` if present) and rebuild the provider registry |
| `/compact` | Keep system prompt, original task, and recent turns |
| `/status` | Session, model, and context details |
| `/context` | Stored vs sent tokens by role |
| `/learning` | Markdown-rendered lessons |
| `/diff` | Current workspace diff in a modal |
| `/clear` | Clear the visible transcript |
| `/help` | Show available commands |
| `/quit` | Exit Symphony (`/exit` also works) |

## Effort levels

`default`, `none`, `low`, `medium`, `high`, `xhigh`, `max`. Availability
depends on the active model.
