# core-server

A FastAPI framework for building chat and research servers on
`symphony-harness`. It owns HTTP run lifecycle and forwards harness
control-plane events without remapping their bodies.

> Not published to PyPI yet. Run it from this workspace.

## Run the server

```sh
ANTHROPIC_API_KEY=your-key-here \
  uv run --package core-server core-server \
  --model anthropic:claude-sonnet-5 --port 8000
```

Creating a run is separate from subscribing to it:

```sh
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"message":"Research this topic","session_id":"chat-1"}'

curl -N http://127.0.0.1:8000/runs/<run_id>/events
```

## HTTP API

- `POST /runs` creates a background run and returns `202`, a `run_id`,
  and an `events_url`.
- `GET /runs/{run_id}` returns queued, running, or terminal status.
- `GET /runs/{run_id}/events` streams existing and future events over SSE.
- `POST /runs/{run_id}/cancel` explicitly cancels a run.
- `GET /models` returns the model-picker registry.
- `GET /health` reports server health and version.

Closing an event connection does not cancel execution. Reconnect with
`Last-Event-ID: <run_id>:<ordinal>`, or `?after=<ordinal>`, to receive
later events. The SSE ID is a server transport cursor; the unchanged event
body still contains the harness's `run_id`, `seq`, `agent_id`, and
`parent_id`.

The default `InProcessRunBackend` is intended for local use. It limits the
process to 64 concurrent and 1,024 outstanding runs, but keeps run records and
event history in memory. For an embedding application, provide a `RunBackend`
that owns queueing, shared state, event retention, cancellation, and session
coordination.

The local limits can be set on `RunManager` and passed through the legacy
`run_manager=` convenience argument to `create_app()`:

```python
from core_server import RunManager, build_config, create_app

app = create_app(
    build_config(),
    run_manager=RunManager(max_concurrent_runs=24, max_outstanding_runs=200),
)
```

When the outstanding limit is reached, `POST /runs` returns `503` with
`Retry-After: 1`. The local manager does not evict completed runs or events;
use an application backend with an explicit retention policy for long-lived
services.

## Embed it

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core_server import RunBackend, build_config, create_router, install_middlewares
from my_application.run_backend import ApplicationRunBackend

config = build_config(model_id="anthropic:claude-sonnet-5")
backend: RunBackend = ApplicationRunBackend(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await backend.shutdown()


app = FastAPI(lifespan=lifespan)
app.include_router(create_router(config, run_backend=backend), prefix="/agent")
install_middlewares(app, config, prefix="/agent")
```

`create_app()` remains available as a standalone convenience wrapper. A
backend receives a `RunSubmission` with the validated request and resolved
`RunContext`. Workers can execute it with `RunExecutor(config)` and an event
sink connected to the application's shared event store. See
[`RunBackend`](src/core_server/runs.py) and
[`RunExecutor`](src/core_server/execution.py) for the interfaces.

No application tools are shipped or enabled by `core_server`. Pass
`core_harness.Tool` instances through `tools=` when an application needs
model-callable capabilities. Subagent spawning is an opt-in harness add-on,
enabled by `enable_subagents=True`.

## Sessions and authorization

Runs sharing a resolved `session_id` execute serially, preventing concurrent
load/update/save races in conversation persistence.

The default context resolver and authorizer are intended for single-tenant
local use. Networked applications should resolve an authenticated principal
and an opaque, namespaced storage session, then authorize every status,
events, and cancellation request:

```python
from fastapi import Request

from core_server import RunContext, build_config, create_app


async def resolve_context(
    request: Request,
    requested_session_id: str | None,
) -> RunContext:
    user_id = request.state.user.id
    chat_id = requested_session_id or create_chat_id()
    return RunContext(
        principal_id=user_id,
        session_id=f"{user_id}:{chat_id}",
    )


async def authorize(request: Request, context: RunContext) -> bool:
    return request.state.user.id == context.principal_id


app = create_app(
    build_config(
        resolve_run_context=resolve_context,
        authorize_run=authorize,
    )
)
```

Returning `404` for unauthorized run IDs avoids disclosing whether another
principal's run exists.

## Add-ons

Add-ons are constructed per run so mutable state is never shared accidentally:

```python
app = create_app(
    build_config(
        addon_factories=[
            lambda context: MyPolicyAddon(principal_id=context.principal_id),
        ],
    )
)
```

`persistence=` mounts `PersistenceAddon`, compaction thresholds mount the
standard compaction add-on, and `enable_subagents=True` creates a fresh
`SubagentAddon` for each run. Use `subagent_factory=` for customized child
configuration.

## Request policy

The strict request schema accepts `message`, optional `conversation`,
`session_id`, `model_id`, and `reasoning_effort`. Reasoning effort is
validated against the public levels from `none` through `max`.
`supported_models=` can restrict model selection; the system prompt, tools,
and add-ons remain server-owned.

Request bodies and conversation history are size-limited. Browser origins are
denied by default; set `cors_origins` explicitly.

Docs: **[core-server](../docs/packages/core-server.md)** ·
[Events](../docs/developer-guide/events.md)

## Development

```sh
uv run --package core-server pytest
```
