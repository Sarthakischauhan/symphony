"""FastAPI application that runs core_harness and streams its events."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from core_ai.types import Message
from core_harness import CoreHarness, HarnessCancelled, HarnessLimitExceeded
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from core_server.config import ServerConfig
from core_server.models import ModelRegistryResponse, RegistryModel, RegistryProvider
from core_server.request_limits import RequestSizeLimitMiddleware
from core_server.sse import SSEEventSink, encode_sse

logger = logging.getLogger(__name__)

PACKAGE_VERSION = "0.2.0"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    conversation: Optional[List[Message]] = None
    session_id: Optional[str] = None
    model_id: Optional[str] = Field(default=None, min_length=1)
    reasoning_effort: Optional[str] = Field(default=None, min_length=1)


def _validate_request(request: RunRequest, config: ServerConfig) -> None:
    if len(request.message) > config.max_message_chars:
        raise HTTPException(status_code=413, detail="Message is too large")
    history = request.conversation or []
    if len(history) > config.max_history_messages:
        raise HTTPException(status_code=413, detail="Conversation has too many messages")
    history_chars = sum(len(message.model_dump_json()) for message in history)
    if history_chars > config.max_history_chars:
        raise HTTPException(status_code=413, detail="Conversation history is too large")
    if request.model_id and request.model_id not in {
        model.slug for model in config.supported_models
    }:
        raise HTTPException(status_code=422, detail="Unsupported model_id")


def _build_harness(
    request: RunRequest,
    config: ServerConfig,
    sink: SSEEventSink,
) -> CoreHarness:
    addons = config.addons_for_run()
    return CoreHarness(
        registry=config.registry,
        model_id=request.model_id or config.model_id,
        system_prompt=config.system_prompt,
        config=config.to_harness_config(),
        reasoning_effort=request.reasoning_effort or config.reasoning_effort,
        tools=list(config.tools),
        sink=sink,
        session_id=request.session_id,
        agent_id=request.session_id,
        addons=addons or None,
    )


async def _run_harness(
    harness: CoreHarness,
    request: RunRequest,
    plane: SSEEventSink,
) -> None:
    try:
        await harness.run(
            request.message,
            conversation=request.conversation,
            session_id=request.session_id,
        )
    except (HarnessCancelled, asyncio.CancelledError):
        logger.info("Harness run cancelled")
    except HarnessLimitExceeded as exc:
        logger.warning("Harness run limit exceeded: %s", exc)
    except Exception:
        # The harness owns terminal failure events; the server records the
        # exception without emitting a duplicate run_failed event.
        logger.exception("Harness run failed")
    finally:
        await plane.close()


async def _iter_sse_frames(
    plane: SSEEventSink,
    task: asyncio.Task[None],
    *,
    disconnect_cancel_timeout: float,
):
    stream_completed = False
    try:
        while True:
            event = await plane.queue.get()
            if event is None:
                stream_completed = True
                break
            yield encode_sse(event)
    finally:
        if stream_completed:
            await task
        elif not task.done():
            await plane.disconnect()
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=disconnect_cancel_timeout)
            except asyncio.TimeoutError:
                logger.warning("Harness cancellation timed out")
            except asyncio.CancelledError:
                raise


def create_app(config: ServerConfig) -> FastAPI:
    app = FastAPI(title="core-server", version=PACKAGE_VERSION)
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=config.max_request_bytes,
    )
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
            "tools": config.model_facing_tool_names(),
        }

    @app.get("/models", response_model=ModelRegistryResponse)
    def models() -> ModelRegistryResponse:
        return ModelRegistryResponse(
            default_provider_id="symphony",
            providers=[
                RegistryProvider(
                    id="symphony",
                    label="Symphony",
                    default_model=config.model_id,
                    models=[
                        RegistryModel(id=model.slug, label=model.label)
                        for model in config.supported_models
                    ],
                )
            ],
        )

    @app.post("/runs")
    async def start_run(request: RunRequest) -> StreamingResponse:
        _validate_request(request, config)
        plane = SSEEventSink(max_queue_size=config.sse_queue_size)
        harness = _build_harness(request, config, plane)

        async def event_stream():
            task = asyncio.create_task(_run_harness(harness, request, plane))
            async for frame in _iter_sse_frames(
                plane,
                task,
                disconnect_cancel_timeout=config.disconnect_cancel_timeout,
            ):
                yield frame

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
