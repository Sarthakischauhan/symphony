# core-server

A FastAPI service for creating agent runs and delivering harness events over Server-Sent Events (SSE). It uses `core_harness` and can host the coding agent. Import name: `core_server`.

**Availability:** workspace-only; it is not currently published on PyPI. Start with the [source installation guide](../getting-started/installation.md).

## Start locally

```sh
uv run --package core-server core-server
```

The default bind address is `127.0.0.1:8000`. See the [CLI reference](../reference/cli.md#core-server) for host, port, and model options. The server has no built-in authentication; do not expose it to an untrusted network without an external auth boundary. See [Security](../../SECURITY.md).

## Embed the application

The application factory can be mounted in an existing ASGI app:

```python
from fastapi import FastAPI
from core_server import create_app

app = FastAPI()
app.mount("/agent", create_app())
```

Configure server model and request policy through the documented environment and application settings. The server streams the harness event contract; see [Control-plane events](../developer-guide/events.md).

For endpoint details, session ownership, add-ons, and request policy, see the [core-server package README](../../core_server/README.md).

## Durable runs

`InProcessRunBackend` keeps runs in memory: a restart loses them. `DurableRunBackend` is a drop-in
`RunBackend` that writes each submission, status change and event to SQLite as it happens, and
resumes unfinished runs when the next process starts:

```python
from core_server import DurableRunBackend, RunExecutor, SQLiteDatabase, SQLitePersistence, SQLiteRunStore, build_config, create_router

db = SQLiteDatabase("runs.db")
config = build_config(persistence=SQLitePersistence(db))  # conversations + per-turn checkpoints
backend = DurableRunBackend(RunExecutor(config), SQLiteRunStore(db))
app.include_router(create_router(config, run_backend=backend))
# at startup:
await backend.recover()
```

A resumed run keeps its run id, session id and event history; ordinals continue, so an SSE client
reconnecting with `Last-Event-ID` sees one stream. A `run_resumed` event (`{"attempt": n}`) marks
the restart. The harness reloads the session's stored conversation and gets a `[resumed]` note with
the original task. A tool call that was in flight is dropped and retried if the model still needs
it, so make tools that change the world idempotent or approval-gated. Shutting down leaves runs
resumable, while `cancel` does not. A run is given up after `max_attempts` restarts (default 3).
