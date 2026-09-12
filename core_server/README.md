# core-server

FastAPI server that wraps `symphony-harness` and streams its control-plane
events over SSE. The Python modules remain `core_server` and `core_harness`.

> Not published to PyPI yet. Run it from this workspace.

```sh
ANTHROPIC_API_KEY=your-key-here \
  uv run --package core-server core-server \
  --model anthropic:claude-sonnet-5 --port 8000
```

```sh
curl -N -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"message":"Say hello"}'
```

Docs: **[core-server](../docs/packages/core-server.md)** ·
[Events](../docs/developer-guide/events.md) ·
[CLI](../docs/reference/cli.md)

The harness is configured with a system prompt, tools, and the usual run
settings. Applications subscribe to the same events the harness already emits
— they are not remapped.

## What it provides

- `create_app(config)` for a FastAPI app
- `ServerConfig` / `build_config()` for prompt, tools, model, and harness
  settings
- `POST /runs` — start a run and stream control-plane events as SSE
- `GET /models` — Chat SDK registry from the live `ModelRegistry` and core_ai
  catalog
- `GET /health` — model and registered tool names

## Embed in your app

The CLI and `build_config()` register every provider whose credential is
present. `GET /models` lists those providers and the core_ai catalog models
they expose. This example uses Anthropic; clients see Anthropic (and any other
registered provider) without an extra allowlist:

```python
from core_harness import Tool
from core_server import build_config, create_app

def echo(text: str) -> str:
    return text

app = create_app(
    build_config(
        model_id="anthropic:claude-sonnet-5",
        system_prompt="You are a concise assistant.",
        tools=[Tool(echo)],
    )
)
```

Pass `supported_models=` only to further restrict `/models` and `/runs`:

```python
from core_server import SupportedModel

app = create_app(
    build_config(
        model_id="anthropic:claude-sonnet-5",
        supported_models=[
            SupportedModel("anthropic:claude-sonnet-5", "Claude Sonnet 5"),
            SupportedModel("anthropic:claude-opus-5", "Claude Opus 5"),
        ],
        tools=[Tool(echo)],
    )
)
```

Each SSE frame uses the harness event name and the `ControlPlaneEvent` JSON
body:

```text
event: text_delta
data: {"event_type":"text_delta","payload":{"turn":0,"delta":"Hello"}}
```

`conversation` can include earlier provider messages and `session_id` selects
the session. `model_id` and `reasoning_effort` can be set per run; otherwise
they fall back to the server default. The system prompt and tools remain
server-owned and cannot be overridden by a run request.

The request schema is strict. Clients must use those snake_case field names;
unknown fields are rejected.

`GET /models` returns the model-picker registry shape. Provider `id`s are the
registry namespaces and each provider includes an absolute models.dev logo
URL. Model IDs are the qualified core_ai routing slugs accepted by
`POST /runs` (for example, `openai:gpt-4.1`).
Each model's `thinkingLevels` contains the supported public reasoning-effort
values (`none` through `max`) from the generated core_ai catalog.
`supported_models` remains an optional extra allowlist over those slugs.

## Harness add-ons

`CoreHarness` does not auto-build persistence, compaction, or `spawn_agent`.
The server mounts those seams from `ServerConfig`:

- `persistence=` — wrapped in `PersistenceAddon` so `session_id` can load and
  save conversations
- `context_compact_threshold` / `context_target_tokens` — mounts
  `compaction_from_config` (`KeepSystemRecentCompactor`)
- `enable_subagents=True` — registers `SubagentAddon` (`spawn_agent`); child
  events share the parent SSE stream and carry `agent_id` / `parent_id`
- `addons=` — extra `Addon` instances (for example a `before_tool` policy).
  The harness no longer has a control-plane `approve` method; deny a tool by
  returning a reason from `Addon.before_tool`

## Environment configuration

The default registry recognizes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY` / `GOOGLE_API_KEY`, and `XAI_API_KEY`, along with `OPENAI_BASE_URL`,
`ANTHROPIC_BASE_URL`, `GEMINI_BASE_URL`, and `XAI_BASE_URL`. Ollama opts in with
`OLLAMA_ENABLED`, `OLLAMA_BASE_URL`, or `OLLAMA_HOST`. Local OpenAI-compatible
servers opt in with `LOCAL_BASE_URL`. Every configured provider is registered.

The server selects its model in this order: an explicit `model_id` / `--model`,
`SYMPHONY_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GEMINI_MODEL`, `GROK_MODEL`,
`XAI_MODEL`, `OLLAMA_MODEL`, `LOCAL_MODEL`, then `default_model_id()` for the
first registered provider (OpenAI → Anthropic → Gemini → Grok → Ollama → local).
Unqualified names beginning with
`claude-`, `gemini-`, or `grok-` are assigned to the corresponding provider;
other unqualified names are assigned to OpenAI. Ensure the selected model's
provider has a credential. For custom deployments, pass an explicit
`ModelRegistry` to `build_config()` or construct `ServerConfig` directly.

No tools are enabled by default. `ask_user` remains available as an explicit
tool, but should only be enabled once the application provides a matching
resume/input flow for the same run. `question_asked` is a product event
emitted through `EventSink.request_user_input`; the SSE sink does not wait
for an answer on the current request.

Run requests and history are size-limited, and the SSE event queue is bounded.
When a client disconnects, the server cancels the `asyncio.Task` that is
awaiting `CoreHarness.run`. The harness then emits `run_cancelled` and raises
`HarnessCancelled`.

The defaults are a 1 MiB request body, 32,000-character user message, 100
history messages, 500,000 serialized history characters, and a 256-event SSE
queue. These can be changed on `ServerConfig`. Browser origins are denied by
default; explicitly set `cors_origins` for browser clients.

## Development

```sh
uv run --package core-server pytest
```
