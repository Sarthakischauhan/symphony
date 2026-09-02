# core-server

`core-server` wraps `symphony-harness`. Applications subscribe to the same
events the harness already emits — they are not remapped. The system prompt
and tools stay server-owned.

> **Not on PyPI yet.** Run it from the workspace. The Python module is
> `core_server`. The console script is `core-server`.

See also the [package README](../../core_server/README.md).

## What it provides

- `create_app(config)` — FastAPI app.
- `ServerConfig` / `build_config()` — prompt, tools, model, harness settings.
- `POST /runs` — start a run and stream control-plane events as SSE.
- `GET /models` — Chat SDK registry for the models `/runs` accepts.
- `GET /health` — model and registered tool names.

## Start the server

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

Each SSE frame uses the harness event name and the `ControlPlaneEvent` JSON
body:

```text
event: text_delta
data: {"event_type":"text_delta","payload":{"turn":0,"delta":"Hello"}}
```

## Embed in your app

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

## Request rules

- `conversation` can include earlier provider messages; `session_id` selects
  the session.
- `model_id` can select a model for one run. Unadvertised slugs are rejected.
- When `supported_models` is omitted, only the default model is exposed. The
  catalog does not auto-advertise every known model.
- No tools are enabled by default. `ask_user` is opt-in until you provide a
  resume/input flow.
- Client disconnect sends the harness cancel command so streams and tools stop
  cleanly.
- Browser origins are denied by default. Set `cors_origins` explicitly.

## Limits

Defaults: 1 MiB request body, 32,000-character user message, 100 history
messages, 500,000 serialized history characters, 256-event SSE queue. Override
on `ServerConfig`.

CLI flags: [CLI](../reference/cli.md). Event names:
[Control-plane events](../developer-guide/events.md).
