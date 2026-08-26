"""A scripted, OpenAI-compatible model server used to record the product demo.

The demo must be reproducible without provider credentials, so this serves the
Responses API shape that `core_ai.providers.openai.OpenAIProvider` consumes and
replays a fixed plan of tool calls. Everything downstream of the provider -- the
harness loop, approvals, real workspace tools, persistence, the TUI -- runs for
real against whatever workspace the agent was pointed at.

Scenes are chosen from the conversation the provider sends back, so the server
stays correct no matter how many turns the harness needs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Iterator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

# Pacing (seconds) so streamed output is legible in a screen recording rather
# than appearing in a single frame.
TEXT_DELAY = 0.012
REASONING_DELAY = 0.016
ARGS_DELAY = 0.02
PRE_TOOL_DELAY = 0.25

BUILD_TASK_STEPS: tuple[dict[str, Any], ...] = (
    {
        "reasoning": "Locating the router module before editing anything.",
        "tool": "search",
        "arguments": {"query": "@router.get", "mode": "content", "path": "app"},
    },
    {
        "reasoning": "Reading the routes file so the patch matches exactly.",
        "tool": "read_file",
        "arguments": {"path": "app/routes.py"},
    },
    {
        "reasoning": "Adding the endpoint next to the existing readiness probe.",
        "tool": "patch",
        "arguments": {
            "path": "app/routes.py",
            "old_str": '@router.get("/ready")\ndef ready() -> dict[str, str]:\n    return {"status": "ready"}\n',
            "new_str": (
                '@router.get("/ready")\n'
                "def ready() -> dict[str, str]:\n"
                '    return {"status": "ready"}\n'
                "\n"
                "\n"
                '@router.get("/health")\n'
                "def health() -> dict[str, str]:\n"
                '    """Liveness probe used by the deployment health check."""\n'
                '    return {"status": "ok"}\n'
            ),
        },
    },
    {
        "reasoning": "Covering the new route with a test.",
        "tool": "write_file",
        "arguments": {
            "path": "tests/test_health.py",
            "content": (
                "from fastapi.testclient import TestClient\n"
                "\n"
                "from app.main import app\n"
                "\n"
                "\n"
                "def test_health_returns_ok() -> None:\n"
                "    response = TestClient(app).get(\"/health\")\n"
                "    assert response.status_code == 200\n"
                '    assert response.json() == {"status": "ok"}\n'
            ),
        },
    },
    {
        "reasoning": "Running the suite to confirm the change works.",
        "tool": "bash",
        "arguments": {"command": "python -m pytest -q"},
    },
)

BUILD_TASK_ANSWER = (
    "Added the liveness probe and a test for it.\n"
    "\n"
    "- `app/routes.py` now exposes `GET /health` returning `{\"status\": \"ok\"}`\n"
    "- `tests/test_health.py` asserts the status code and body\n"
    "\n"
    "```python\n"
    '@router.get("/health")\n'
    "def health() -> dict[str, str]:\n"
    '    return {"status": "ok"}\n'
    "```\n"
    "\n"
    "`python -m pytest -q` passes. Want me to wire it into the deployment probe config too?"
)

PLAN_STEPS: tuple[dict[str, Any], ...] = (
    {
        "reasoning": "Reading the app before proposing a plan.",
        "tool": "search",
        "arguments": {"query": "def ", "mode": "content", "path": "app"},
    },
    {
        "reasoning": "Checking how the app is wired together.",
        "tool": "read_file",
        "arguments": {"path": "app/main.py"},
    },
)

PLAN_ANSWER = (
    "## Goal\n"
    "Add API-key authentication to every write route.\n"
    "\n"
    "## Steps\n"
    "1. Add `app/security.py` with an `require_api_key` FastAPI dependency that\n"
    "   reads `SYMPHONY_API_KEY` and raises `401` on mismatch.\n"
    "2. Attach the dependency to the router's mutating routes only, leaving\n"
    "   `/ready` and `/health` unauthenticated so probes keep working.\n"
    "3. Add `tests/test_security.py` covering a missing key, a wrong key, and a\n"
    "   valid key.\n"
    "4. Document the new environment variable in `README.md`.\n"
    "\n"
    "## Risks\n"
    "- Probes must stay public or deployments will fail their health checks.\n"
    "- Existing clients need the key before this ships; gate it behind config.\n"
)


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _chunks(text: str, size: int = 14) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


def _completed(input_tokens: int, output_tokens: int, reasoning_tokens: int) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
                "total_tokens": input_tokens + output_tokens,
            }
        },
    }


def _plan_mode(payload: dict[str, Any]) -> bool:
    """Plan mode only exposes the read-only tools."""
    names = {tool.get("name") for tool in payload.get("tools") or []}
    return "patch" not in names


def _completed_tool_calls(payload: dict[str, Any]) -> int:
    """Count tool results already returned, which is the scene index."""
    return sum(
        1
        for item in payload.get("input") or []
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    )


async def _stream_step(step: dict[str, Any], *, index: int, prompt_tokens: int):
    reasoning = step["reasoning"]
    for piece in _chunks(reasoning, 10):
        yield _sse(
            {
                "type": "response.reasoning_summary_text.delta",
                "summary_index": 0,
                "delta": piece,
            }
        )
        await asyncio.sleep(REASONING_DELAY)

    await asyncio.sleep(PRE_TOOL_DELAY)

    item_id = f"fc_{index}"
    call_id = f"call_{index}_{step['tool']}"
    yield _sse(
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": item_id,
                "type": "function_call",
                "call_id": call_id,
                "name": step["tool"],
            },
        }
    )

    arguments = json.dumps(step["arguments"])
    for piece in _chunks(arguments, 48):
        yield _sse(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": item_id,
                "output_index": 0,
                "delta": piece,
            }
        )
        await asyncio.sleep(ARGS_DELAY)

    yield _sse(_completed(prompt_tokens, len(arguments) // 4 + 12, len(reasoning) // 4))
    yield b"data: [DONE]\n\n"


async def _stream_answer(text: str, *, prompt_tokens: int):
    for piece in _chunks(text):
        yield _sse(
            {
                "type": "response.output_text.delta",
                "content_index": 0,
                "delta": piece,
            }
        )
        await asyncio.sleep(TEXT_DELAY)
    yield _sse(_completed(prompt_tokens, len(text) // 4, 0))
    yield b"data: [DONE]\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="Symphony demo model server")

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {
            "data": [
                {"id": "gpt-5.4", "object": "model"},
                {"id": "gpt-5.4-mini", "object": "model"},
            ]
        }

    @app.post("/v1/responses")
    async def responses(request: Request) -> StreamingResponse:
        payload = await request.json()
        steps = PLAN_STEPS if _plan_mode(payload) else BUILD_TASK_STEPS
        answer = PLAN_ANSWER if _plan_mode(payload) else BUILD_TASK_ANSWER
        index = _completed_tool_calls(payload)
        # Rough but stable stand-in for real prompt accounting.
        prompt_tokens = 1_200 + index * 480

        if index < len(steps):
            stream = _stream_step(steps[index], index=index, prompt_tokens=prompt_tokens)
        else:
            stream = _stream_answer(answer, prompt_tokens=prompt_tokens)

        return StreamingResponse(stream, media_type="text/event-stream")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
