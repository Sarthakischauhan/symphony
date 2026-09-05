# Environment

Keys can live in `.env`. First-run onboarding and `/provider` write
`~/.symphony/.env`. Load order is process environment, then workspace
`.env` if present, then `~/.symphony/.env`. `/reload` in the TUI reloads
those files and rebuilds the registry.


## Provider credentials

| Variable | Provider |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini |
| `XAI_API_KEY` | Grok |

## Model selection

| Variable | Role |
| --- | --- |
| `SYMPHONY_MODEL` | Highest-priority `provider:model` override |
| `OPENAI_MODEL` | OpenAI default when that provider is registered |
| `ANTHROPIC_MODEL` | Anthropic default |
| `GEMINI_MODEL` | Gemini default |
| `GROK_MODEL` or `XAI_MODEL` | Grok default |

## Base URLs

| Variable | Role |
| --- | --- |
| `OPENAI_BASE_URL` | Compatible OpenAI-style endpoints |
| `ANTHROPIC_BASE_URL` | Anthropic-compatible endpoints |
| `GEMINI_BASE_URL` | Gemini-compatible endpoints |
| `XAI_BASE_URL` | xAI-compatible endpoints |

## Catalog generation (maintainers)

These only affect `core_ai/scripts/generate_models.py` and the opt-in build
refresh. A normal install or build never reads them and never contacts
models.dev.

| Variable | Role |
| --- | --- |
| `CORE_AI_GENERATE_STRICT` | `1`: the script fails instead of keeping the old snapshot when models.dev is unreachable |
| `CORE_AI_MODELS_DEV` | `0`: the script skips the network and rewrites from the existing snapshot |
| `MODELS_DEV_URL` | Mirror or test endpoint instead of `https://models.dev/api.json` |
| `CORE_AI_REFRESH_CATALOG` | `1` at build time: the Hatch hook refreshes the catalog (strict). Unset by default |
