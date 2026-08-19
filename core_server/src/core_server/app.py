"""FastAPI application that runs core_harness and streams its events."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from core_ai.types import Message
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core_harness import CoreHarness

from core_server.config import ServerConfig
from core_server.sse import SSEControlPlane, encode_sse


class RunRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation: Optional[List[Message]] = None
    session_id: Optional[str] = None
    system_prompt: Optional[str] = None
    model_id: Optional[str] = None


def create_app(config: ServerConfig) -> FastAPI:
    app = FastAPI(title="core-server", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "model_id": config.model_id,
            "tools": [tool.name for tool in config.tools],
        }

    @app.post("/runs")
    async def start_run(request: RunRequest) -> StreamingResponse:
        plane = SSEControlPlane()
        harness = CoreHarness(
            registry=config.registry,
            model_id=request.model_id or config.model_id,
            system_prompt=request.system_prompt or config.system_prompt,
            tools=list(config.tools),
            control_plane=plane,
            persistence=config.persistence,
            session_id=request.session_id,
            max_turns=config.max_turns,
            context_limits=config.context_limits,
            context_warn_threshold=config.context_warn_threshold,
            context_compact_threshold=config.context_compact_threshold,
            tool_result_max_chars=config.tool_result_max_chars,
            context_target_tokens=config.context_target_tokens,
        )

        async def run_harness() -> None:
            try:
                await harness.run(
                    request.message,
                    conversation=request.conversation,
                    session_id=request.session_id,
                )
            except Exception:
                pass
            finally:
                await plane.close()

        async def event_stream():
            task = asyncio.create_task(run_harness())
            try:
                while True:
                    event = await plane.queue.get()
                    if event is None:
                        break
                    yield encode_sse(event)
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app
