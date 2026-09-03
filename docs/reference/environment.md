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

## Model selection

| Variable | Role |
| --- | --- |
| `SYMPHONY_MODEL` | Highest-priority `provider:model` override |
| `OPENAI_MODEL` | OpenAI default when that provider is registered |
| `ANTHROPIC_MODEL` | Anthropic default |
| `GEMINI_MODEL` | Gemini default |

## Base URLs

| Variable | Role |
| --- | --- |
| `OPENAI_BASE_URL` | Compatible OpenAI-style endpoints |
| `ANTHROPIC_BASE_URL` | Anthropic-compatible endpoints |
| `GEMINI_BASE_URL` | Gemini-compatible endpoints |

## Catalog generation

| Variable | Role |
| --- | --- |
| `CORE_AI_MODELS_DEV` | Set to `0` to skip the models.dev refresh |
| `MODELS_DEV_URL` | Mirror or test endpoint for the catalog |
| `CORE_AI_GENERATE_STRICT` | Fail manual refresh on provider errors |
