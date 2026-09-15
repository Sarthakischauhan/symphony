# core-server

`core-server` is the FastAPI framework for building chat and research
servers on `symphony-harness`. It owns HTTP run lifecycle and forwards
harness control-plane events without remapping their bodies.

> **Not on PyPI yet.** The Python module is `core_server`; the workspace
> console script is `core-server`.

## Run lifecycle

Execution is independent of an SSE connection:

| Endpoint | Purpose |
| --- | --- |
| `POST /runs` | Create a background run; returns `202`, `run_id`, and `events_url` |
| `GET /runs/{run_id}` | Read queued, running, completed, failed, or cancelled status |
| `GET /runs/{run_id}/events` | Replay existing events, then stream new events |
| `POST /runs/{run_id}/cancel` | Explicitly cancel the run and its child agents |
| `GET /models` | Read the model-picker registry |
| `GET /health` | Read health and package version |

```sh
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"message":"Research this topic","session_id":"chat-1"}'

curl -N http://127.0.0.1:8000/runs/<run_id>/events
```

Closing the event stream does not cancel the run. Resume after an observed
event with `Last-Event-ID: <run_id>:<ordinal>` or `?after=<ordinal>`.
Transport ordinals cover the whole combined stream, including child-agent
events. Event bodies retain the original harness `run_id`, `seq`,
`session_id`, `agent_id`, and `parent_id`.

The default `InProcessRunBackend` is a convenience backend for local use. It
limits the process to 64 concurrent and 1,024 outstanding runs, but its run
records and event histories remain in memory and are not shared across worker
processes. Production applications should provide a `RunBackend` that owns
queueing, shared run/event storage, retention, cancellation, and distributed
session ordering.

Set `RunManager(max_concurrent_runs=..., max_outstanding_runs=...)` to tune
the local limits and pass it to `create_app(run_manager=...)`. At capacity,
`POST /runs` returns `503` with `Retry-After: 1`. The local manager retains
completed records and event history indefinitely, so long-lived services
should use a backend with an explicit retention policy.

## Embed the framework

```python
from core_server import build_config, create_app

app = create_app(
    build_config(
        model_id="anthropic:claude-sonnet-5",
        system_prompt="You are a careful research assistant.",
        enable_subagents=True,
    )
)
```

`create_app()` is the standalone convenience wrapper. To mount the routes in
an application that owns authentication, middleware, and lifespan, include
the router and manage the backend with the host app:

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

The backend receives a `RunSubmission` containing the validated request and
resolved `RunContext`. A worker can execute it with `RunExecutor(config)` and
an event sink connected to the backend's shared event store. The backend
implements `submit`, `get`, `events`, `cancel`, and `shutdown`; see
[`RunBackend`](../../core_server/src/core_server/runs.py) and
[`RunExecutor`](../../core_server/src/core_server/execution.py) for the
contracts. This keeps job dispatch, persistence, retention, and session
coordination owned by the consuming application.

No application tools are shipped or enabled by `core_server`. Applications
may pass `core_harness.Tool` instances through `tools=`. Subagent spawning
is an opt-in harness capability created by `enable_subagents=True`.

## Sessions and access control

Runs with the same resolved session ID execute serially. This prevents two
requests from loading the same conversation revision and overwriting each
other.

The default resolver and authorizer are for single-tenant local use. A
networked application should provide both hooks:

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

Authorization runs before status, event, and cancellation access.
Unauthorized IDs return `404`.

## Add-ons and subagents

`addon_factories` receives the resolved `RunContext` and must return a new
add-on for that run:

```python
app = create_app(
    build_config(
        addon_factories=[
            lambda context: MyPolicyAddon(principal_id=context.principal_id),
        ],
    )
)
```

`persistence=` mounts `PersistenceAddon`; configured compaction thresholds
mount the standard compaction add-on; and `enable_subagents=True` mounts a
fresh `SubagentAddon`. Supply `subagent_factory=` to customize background
behavior, child models, tool inheritance, or child add-ons.

Child lifecycle and output events appear in the same server stream as the
parent. See [control-plane events](../developer-guide/events.md).

## Request and model policy

The strict run request accepts `message`, optional `conversation`,
`session_id`, `model_id`, and `reasoning_effort`. Reasoning effort must
be one of the advertised public levels. The system prompt, tools, and add-ons
cannot be overridden by a run request.

`supported_models=` optionally restricts `GET /models` and per-run model
selection. Request bodies and histories are size-limited. Browser origins are
denied by default; configure `cors_origins` explicitly.

See also the [package README](../../core_server/README.md).
