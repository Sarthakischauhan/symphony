# core-server

FastAPI server that wraps `core_harness` and streams its control-plane events over SSE.

The harness is configured with a system prompt, tools, and the usual run settings. Applications subscribe to the same events the harness already emits — they are not remapped.

## What it provides

- `create_app(config)` for a FastAPI app
- `ServerConfig` / `build_config()` for prompt, tools, model, and harness settings
- `POST /runs` — start a run and stream control-plane events as SSE
- `GET /models` — Chat SDK registry for the models accepted by `/runs`
- `GET /health` — model and registered tool names

## Example

The CLI and `build_config()` register every provider whose credential is present.
This example uses Anthropic and advertises two models to clients:

```python
from core_harness import Tool
from core_server import SupportedModel, build_config, create_app


def echo(text: str) -> str:
    return text


app = create_app(
    build_config(
        model_id="anthropic:claude-sonnet-5",
        supported_models=[
            SupportedModel("anthropic:claude-sonnet-5", "Claude Sonnet 5"),
            SupportedModel("anthropic:claude-opus-5", "Claude Opus 5"),
        ],
        system_prompt="You are a concise assistant.",
        tools=[Tool(echo)],
    )
)
```

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

Each SSE frame uses the harness event name and the `ControlPlaneEvent` JSON body:

```
event: text_delta
data: {"event_type":"text_delta","payload":{"turn":0,"delta":"Hello"}}
```

`conversation` can include earlier provider messages and `session_id` selects the
session. `model_id` can select a model for an individual run and otherwise falls
back to the server default. The system prompt and tools remain server-owned and
cannot be overridden by a run request.

`GET /models` returns the Chat SDK `RegistryConfig` shape. Each model `id` is the
exact slug accepted as `model_id` by `POST /runs`; unadvertised slugs are rejected.
When `supported_models` is omitted, only the configured default model is exposed.
The generated `core_ai` catalog and registered credentials do not automatically
advertise every known model; `supported_models` remains the server allowlist.

## Environment configuration

The default registry recognizes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and
`GEMINI_API_KEY` / `GOOGLE_API_KEY`, along with `OPENAI_BASE_URL`,
`ANTHROPIC_BASE_URL`, and `GEMINI_BASE_URL`. Every provider with a credential is
registered.

The server selects its model in this order: an explicit `model_id` / `--model`,
`SYMPHONY_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GEMINI_MODEL`, then
`openai:gpt-5.6-luna`. Unqualified names beginning with `claude-` or `gemini-`
are assigned to the corresponding provider; other unqualified names are assigned
to OpenAI. Ensure the selected model's provider has a credential. For custom
deployments, pass an explicit `ModelRegistry` to `build_config()` or construct
`ServerConfig` directly.

No tools are enabled by default. `ask_user` remains available as an explicit tool,
but should only be enabled once the application provides a matching resume/input
flow for the same run.

Run requests and history are size-limited, and the SSE event queue is bounded.
When a client disconnects, the server sends the harness cancellation command so
active model streams and tools stop cleanly and the harness records `run_cancelled`.

The defaults are a 1 MiB request body, 32,000-character user message, 100 history
messages, 500,000 serialized history characters, and a 256-event SSE queue. These
can be changed on `ServerConfig`. Browser origins are denied by default; explicitly
set `cors_origins` for browser clients.

## Development

```sh
uv run --package core-server pytest
```
