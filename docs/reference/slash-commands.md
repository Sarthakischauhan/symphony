# Slash commands

Type `/` in the composer to discover commands. Tab or Enter selects from the
menu.

| Command | What it does |
| --- | --- |
| `/model [id]` | Show the credential-filtered catalog, or switch model |
| `/mode [mode]` | View or switch **build** / **plan** |
| `/effort [level]` | Set reasoning effort (`none` … `max`) |
| `/plan [text]` | Enter plan mode; with text, submit it as the next planning turn |
| `/plans [name]` | Pick or open a saved workspace plan |
| `/provider [name]` | Add or update a provider API key (OpenAI, Anthropic, Gemini, Grok) |
| `/new` | Start a fresh persisted session |
| `/reload` | Reload `~/.symphony/.env` (and workspace `.env` if present) and rebuild the provider registry |
| `/compact` | Summarize older turns with the model; keep system prompt, original task, and recent turns |
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
