"""FastAPI application for connection-independent harness runs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from core_harness import CoreHarness, EventSink, HarnessCancelled, HarnessLimitExceeded
from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from core_server.catalog import is_accepted_model, model_registry_response
from core_server.config import ServerConfig
from core_server.models import (
    ModelRegistryResponse,
    RunAccepted,
    RunContext,
    RunRequest,
    RunStatusResponse,
)
from core_server.request_limits import RequestSizeLimitMiddleware
from core_server.runs import RunManager, RunNotFoundError, RunRecord, parse_last_event_id
from core_server.sse import encode_sse

logger = logging.getLogger(__name__)

PACKAGE_VERSION = "0.4.0"


def _validate_request(run: RunRequest, config: ServerConfig) -> None:
    if len(run.message) > config.max_message_chars:
        raise HTTPException(status_code=413, detail="Message is too large")
    history = run.conversation or []
    if len(history) > config.max_history_messages:
        raise HTTPException(status_code=413, detail="Conversation has too many messages")
    history_chars = sum(len(message.model_dump_json()) for message in history)
    if history_chars > config.max_history_chars:
        raise HTTPException(status_code=413, detail="Conversation history is too large")
    if run.model_id and not is_accepted_model(config, run.model_id):
        raise HTTPException(status_code=422, detail="Unsupported model_id")


def _build_harness(
    run: RunRequest,
    context: RunContext,
    config: ServerConfig,
    sink: EventSink,
    *,
    run_id: str,
) -> CoreHarness:
    return CoreHarness(
        registry=config.registry,
        model_id=run.model_id or config.model_id,
        system_prompt=config.system_prompt,
        config=config.to_harness_config(),
        reasoning_effort=run.reasoning_effort or config.reasoning_effort,
        tools=list(config.tools),
        sink=sink,
        session_id=context.session_id,
        agent_id=run_id,
        addons=config.addons_for_run(context) or None,
    )


async def _run_harness(
    harness: CoreHarness,
    run: RunRequest,
    *,
    run_id: str,
    session_id: str,
) -> None:
    try:
        await harness.run(
            run.message,
            conversation=run.conversation,
            session_id=session_id,
        )
    except HarnessCancelled:
        logger.info("Harness run %s cancelled", run_id)
    except HarnessLimitExceeded as exc:
        logger.warning("Harness run %s limit exceeded: %s", run_id, exc)
    except Exception:
        # The harness emits the terminal failure event before propagating.
        logger.exception("Harness run %s failed", run_id)


async def _authorized_record(
    request: Request,
    config: ServerConfig,
    manager: RunManager,
    run_id: str,
) -> RunRecord:
    try:
        record = await manager.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found") from None
    if not await config.authorize_run(request, record.context):
        raise HTTPException(status_code=404, detail="Run not found")
    return record


def create_app(
    config: ServerConfig,
    *,
    run_manager: RunManager | None = None,
) -> FastAPI:
    manager = run_manager or RunManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.shutdown()

    app = FastAPI(title="core-server", version=PACKAGE_VERSION, lifespan=lifespan)
    app.state.run_manager = manager
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=config.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": PACKAGE_VERSION}

    @app.get("/models", response_model=ModelRegistryResponse)
    def models() -> ModelRegistryResponse:
        return model_registry_response(config)

    @app.post(
        "/runs",
        response_model=RunAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def start_run(run: RunRequest, request: Request) -> RunAccepted:
        _validate_request(run, config)
        context = await config.resolve_run_context(request, run.session_id)
        if not context.session_id.strip():
            raise HTTPException(status_code=500, detail="Run context has an empty session_id")

        async def execute(run_id: str, sink: EventSink) -> None:
            harness = _build_harness(
                run,
                context,
                config,
                sink,
                run_id=run_id,
            )
            await _run_harness(
                harness,
                run,
                run_id=run_id,
                session_id=context.session_id,
            )

        record = await manager.start(context, execute)
        return RunAccepted(
            run_id=record.run_id,
            session_id=context.session_id,
            status=record.status,
            events_url=f"/runs/{record.run_id}/events",
        )

    @app.get("/runs/{run_id}", response_model=RunStatusResponse)
    async def get_run(run_id: str, request: Request) -> RunStatusResponse:
        record = await _authorized_record(request, config, manager, run_id)
        return record.response()

    @app.get("/runs/{run_id}/events")
    async def stream_run_events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        await _authorized_record(request, config, manager, run_id)
        cursor = max(after, parse_last_event_id(last_event_id, run_id))

        async def event_stream() -> AsyncIterator[str]:
            async for ordinal, event in manager.events(run_id, after=cursor):
                yield encode_sse(event, event_id=f"{run_id}:{ordinal}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/runs/{run_id}/cancel", response_model=RunStatusResponse)
    async def cancel_run(run_id: str, request: Request) -> RunStatusResponse:
        await _authorized_record(request, config, manager, run_id)
        record = await manager.cancel(run_id)
        task = record.task
        if task is not None and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
        return record.response()

    return app


__all__ = ["PACKAGE_VERSION", "RunRequest", "create_app"]
