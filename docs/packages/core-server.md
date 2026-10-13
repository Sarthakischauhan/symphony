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
