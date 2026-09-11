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

## Local providers

Ollama and generic OpenAI-compatible servers (LM Studio, vLLM, llama.cpp,
SGLang) are **opt-in**. Symphony does not probe `localhost` on startup.

| Variable | Role |
| --- | --- |
| `OLLAMA_ENABLED=1` | Register Ollama at `http://localhost:11434/v1` |
| `OLLAMA_BASE_URL` | OpenAI-compatible Ollama URL (implies opt-in) |
| `OLLAMA_HOST` | Native Ollama host, e.g. `127.0.0.1:11434` (implies opt-in) |
| `OLLAMA_API_KEY` | Optional; dummy `ollama` is used when unset |
| `LOCAL_BASE_URL` | Required to register a local OpenAI-compatible server |
| `LOCAL_API_KEY` | Optional; dummy `local` is used when unset |

`/provider ollama` writes `OLLAMA_BASE_URL` (blank submit uses the default).
`/provider local` asks for the base URL.

Pulled models are discovered at registry build (`/api/tags` for Ollama,
`/v1/models` for local) and registered into the runtime catalog so `/model`
can list them. They are not added to the checked-in models.dev snapshot.

## Model selection

| Variable | Role |
| --- | --- |
| `SYMPHONY_MODEL` | Highest-priority `provider:model` override |
| `OPENAI_MODEL` | OpenAI default when that provider is registered |
| `ANTHROPIC_MODEL` | Anthropic default |
| `GEMINI_MODEL` | Gemini default |
| `GROK_MODEL` or `XAI_MODEL` | Grok default |
| `OLLAMA_MODEL` | Ollama default when that provider is registered |
| `LOCAL_MODEL` | Local default when that provider is registered |

## Base URLs

| Variable | Role |
| --- | --- |
| `OPENAI_BASE_URL` | Compatible OpenAI-style endpoints |
| `ANTHROPIC_BASE_URL` | Anthropic-compatible endpoints |
| `GEMINI_BASE_URL` | Gemini-compatible endpoints |
| `XAI_BASE_URL` | xAI-compatible endpoints |
| `OLLAMA_BASE_URL` | Ollama OpenAI-compatible endpoint |
| `LOCAL_BASE_URL` | Local OpenAI-compatible endpoint |

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
