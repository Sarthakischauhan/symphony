# Environment

Keys can live in `.env`. First-run onboarding and `/provider` write
`~/.symphony/.env`. ChatGPT, Claude, and xAI subscription logins write
`~/.symphony/oauth/<provider>.json` (mode `0600`). Load order for keys is
process environment, then workspace `.env` if present, then
`~/.symphony/.env`. `/reload` in the TUI reloads those files, re-reads
OAuth tokens, and rebuilds the registry.

By default, an API key in the environment wins over a stored subscription token
for the same provider. Choosing **Sign in with …** in `/provider` records the
subscription choice and makes it win; choosing **API key** records the reverse.
The setting is stored as `SYMPHONY_<PROVIDER>_AUTH` in `~/.symphony/.env`.

You can also select explicitly with `SYMPHONY_OPENAI_AUTH=oauth` (or `key`),
and similarly for Anthropic or Grok.


## Provider credentials

| Variable | Provider |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI (platform key). Alternatively sign in with ChatGPT via `/provider`. |
| `ANTHROPIC_API_KEY` | Anthropic. Alternatively paste a `claude setup-token` via `/provider`. |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini |
| `XAI_API_KEY` | Grok (console API key at `api.x.ai`). Alternatively sign in with xAI via `/provider` (CLI chat proxy). |

## Subscription login

`/provider` (and first-run onboarding) offers **Sign in with …** for
OpenAI, Anthropic, and Grok:

| Provider | What to do |
| --- | --- |
| OpenAI | Browser PKCE against ChatGPT. Symphony listens on `http://localhost:1455/auth/callback`. If the tab does not bounce back, paste that localhost URL. Tokens call `https://chatgpt.com/backend-api/codex`. |
| Anthropic | Preferred: run `claude setup-token` (Claude Code) and paste the token. Alternative: open the shown Claude authorize URL and paste the `code#state` from the redirect. |
| Grok | RFC 8628 device login. Open the shown URL, enter the user code, wait. Subscription traffic goes to `https://cli-chat-proxy.grok.com/v1`. An `XAI_API_KEY` still uses the console API at `https://api.x.ai/v1`. |

Gemini, Ollama, and local servers stay API-key / endpoint based.

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

## Langfuse (optional)

| Variable | Role |
| --- | --- |
| `LANGFUSE_PUBLIC_KEY` | Langfuse project public key (`pk-lf-...`) |
| `LANGFUSE_SECRET_KEY` | Langfuse project secret key (`sk-lf-...`) |
| `LANGFUSE_BASE_URL` | Cloud region or self-hosted URL (default `https://cloud.langfuse.com`) |

Both keys must be set or `LangfuseAddon` stays silent. The Python SDK is an
optional extra (`symphony-code[langfuse]`). See
[`docs/user-guide/langfuse.md`](../user-guide/langfuse.md).

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
