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

```python
from core_ai import ModelRegistry, OpenAIProvider
from core_harness import Tool
from core_server import ServerConfig, SupportedModel, create_app


def echo(text: str) -> str:
    return text


registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

app = create_app(
    ServerConfig(
        registry=registry,
        model_id="openai:gpt-4o-mini",
        supported_models=[
            SupportedModel("openai:gpt-4o-mini", "GPT-4o mini"),
            SupportedModel("openai:gpt-4.1", "GPT-4.1"),
        ],
        system_prompt="You are a concise assistant.",
        tools=[Tool(echo)],
    )
)
```

```sh
uv run --package core-server core-server --port 8000
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
