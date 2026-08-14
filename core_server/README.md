# core-server

FastAPI server that wraps `core_harness` and streams its control-plane events over SSE.

The harness is configured with a system prompt, tools, and the usual run settings. Applications subscribe to the same events the harness already emits — they are not remapped.

## What it provides

- `create_app(config)` for a FastAPI app
- `ServerConfig` / `build_config()` for prompt, tools, model, and harness settings
- `POST /runs` — start a run and stream control-plane events as SSE
- `GET /health` — model and registered tool names

## Example

```python
from core_ai import ModelRegistry, OpenAIProvider
from core_harness import Tool
from core_server import ServerConfig, create_app


def echo(text: str) -> str:
    return text


registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

app = create_app(
    ServerConfig(
        registry=registry,
        model_id="openai:gpt-4o-mini",
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

`session_id`, `system_prompt`, and `model_id` can be overridden per request. Tools stay on the server config.

## Development

```sh
uv run --package core-server pytest
```
