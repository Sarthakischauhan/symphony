"""Launch the coding agent TUI against the scripted demo model server.

Used to record the documentation walkthrough. The harness, approvals, workspace
tools, and persistence all run for real; only the model responses are scripted so
the demo is reproducible without provider credentials.

    uv run --package coding-agent python coding_agent/scripts/demo/run_demo.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

DEMO_MODEL = "openai:gpt-5.4"

SEED_FILES: dict[str, str] = {
    "app/__init__.py": "",
    "app/main.py": '''"""Checkout service."""

from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="Checkout service")
app.include_router(router)
''',
    "app/routes.py": '''"""HTTP routes for the checkout service."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/orders/{order_id}")
def get_order(order_id: str) -> dict[str, str]:
    return {"id": order_id, "state": "pending"}


@router.post("/orders")
def create_order(total_cents: int) -> dict[str, int]:
    return {"id": 1, "total_cents": total_cents}


@router.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}
''',
    "tests/__init__.py": "",
    "tests/test_orders.py": '''from fastapi.testclient import TestClient

from app.main import app


def test_get_order() -> None:
    response = TestClient(app).get("/orders/abc")
    assert response.status_code == 200
    assert response.json()["state"] == "pending"
''',
    "README.md": """# checkout-service

Small FastAPI service used for the Symphony coding agent walkthrough.

## Running tests

```sh
python -m pytest -q
```
""",
    # Keep unrelated dependency warnings out of the recorded tool output.
    "pytest.ini": "[pytest]\ntestpaths = tests\nfilterwarnings = ignore\n",
    ".gitignore": "__pycache__/\n.pytest_cache/\n.symphony/\n",
}


def seed_workspace(root: Path, *, reset: bool, git: bool = True) -> Path:
    """Create the sample project the agent edits during the demo."""
    if reset and root.exists():
        shutil.rmtree(root)
    for relative, content in SEED_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if git:
        _git_init(root)
    return root


def _git_init(root: Path) -> None:
    """Commit the seed so `/diff` has a real baseline to compare against."""
    if (root / ".git").exists():
        return
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Symphony Demo",
        "GIT_AUTHOR_EMAIL": "demo@example.com",
        "GIT_COMMITTER_NAME": "Symphony Demo",
        "GIT_COMMITTER_EMAIL": "demo@example.com",
    }
    commands = (
        ["git", "init", "--quiet", "--initial-branch", "main"],
        ["git", "add", "."],
        ["git", "commit", "--quiet", "-m", "checkout service baseline"],
    )
    for command in commands:
        subprocess.run(command, cwd=root, env=env, check=True, capture_output=True)


def wait_for_port(host: str, port: int, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"demo model server did not start on {host}:{port}")


def start_model_server(host: str, port: int) -> None:
    import uvicorn

    from mock_model_server import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host=host, port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    wait_for_port(host, port)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default="/tmp/symphony-demo/checkout-service",
        help="Demo project the agent edits (recreated on each launch)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Reuse an existing demo workspace instead of recreating it",
    )
    args = parser.parse_args()

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    workspace = seed_workspace(Path(args.workspace), reset=not args.keep_workspace)
    start_model_server(args.host, args.port)

    os.environ["OPENAI_API_KEY"] = "demo-scripted-model"
    os.environ["OPENAI_BASE_URL"] = f"http://{args.host}:{args.port}/v1"
    os.environ["SYMPHONY_MODEL"] = DEMO_MODEL

    from coding_agent.tui.app import run_tui

    run_tui(workspace=workspace, model_id=DEMO_MODEL, enable_learning=False)


if __name__ == "__main__":
    main()
