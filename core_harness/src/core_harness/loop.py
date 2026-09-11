"""The harness run: stream a model turn, run tools, repeat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from core_ai.content import text_from_content
from core_ai.types import Content, Message, StreamEvent

from core_harness.addons.subagent.background import wait_for_child_result
from core_harness.context import (
    bound_tool_result,
    estimate_completion_tokens,
    estimate_prompt_tokens,
    messages_for_model,
)
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import HarnessResult, PendingToolCall, ToolCall, ToolResult, UsageTotals
from core_harness.models import StreamedTurn, TurnResult
from core_harness.tools import current_tool_call_id

if TYPE_CHECKING:
    from core_harness.harness import CoreHarness

logger = logging.getLogger(__name__)


async def stream_model_turn(
    runner: Any,
    messages: List[Message],
    *,
    turn: int,
    usage: UsageTotals,
    estimated_message_tokens: int,
) -> StreamedTurn:
    """Consume the provider stream; mutate ``usage``. Return text, calls, budget."""
    streamed = StreamedTurn(estimated_message_tokens=estimated_message_tokens)
    streamed.budget_tokens = estimated_message_tokens
    async for event in iter_provider_events(runner, messages):
        await dispatch_stream_event(
            event,
            turn=turn,
            usage=usage,
            streamed=streamed,
            emit=runner.emit,
        )

    if not streamed.saw_usage:
        await _emit_estimated_usage(runner, messages, turn=turn, usage=usage, streamed=streamed)

    await runner.emit(
        "turn_completed",
        {"turn": turn, "had_tool_calls": bool(streamed.pending_calls)},
    )
    return streamed


async def dispatch_stream_event(
    event: StreamEvent,
    *,
    turn: int,
    usage: UsageTotals,
    streamed: StreamedTurn,
    emit: Callable[..., Awaitable[None]],
) -> None:
    """Apply one provider event to stream state and the event sink."""
    if event.type == "text_delta" and event.delta:
        streamed.assistant_text += event.delta
        await emit(
            "text_delta",
            {"turn": turn, "delta": event.delta},
        )
    elif event.type == "reasoning_delta" and event.delta:
        summary_index = event.content_index
        streamed.reasoning_texts[summary_index] = (
            streamed.reasoning_texts.get(summary_index, "") + event.delta
        )
        await emit(
            "reasoning_delta",
            {
                "turn": turn,
                "summary_index": summary_index,
                "delta": event.delta,
                "text": streamed.reasoning_texts[summary_index],
            },
        )
    elif event.type == "toolcall_start":
        streamed.pending_calls[event.content_index] = PendingToolCall(
            id=event.tool_call_id or f"toolcall-{turn}-{event.content_index}",
            name=event.tool_name,
            metadata=dict(event.tool_call_metadata or {}),
        )
        await emit(
            "tool_call_started",
            {
                "turn": turn,
                "tool_call_id": streamed.pending_calls[event.content_index].id,
                "tool_name": event.tool_name,
            },
        )
    elif event.type == "toolcall_delta" and event.delta:
        pending = streamed.pending_calls.setdefault(
            event.content_index,
            PendingToolCall(id=f"toolcall-{turn}-{event.content_index}"),
        )
        pending.arguments_json += event.delta
        await emit(
            "tool_call_delta",
            {
                "turn": turn,
                "tool_call_id": pending.id,
                "delta": event.delta,
            },
        )
    elif event.type == "retry":
        if event.retry_resets_stream:
            streamed.assistant_text = ""
            streamed.reasoning_texts.clear()
            streamed.pending_calls.clear()
            usage.prompt_tokens -= streamed.attempt_usage.prompt_tokens
            usage.completion_tokens -= streamed.attempt_usage.completion_tokens
            usage.reasoning_tokens -= streamed.attempt_usage.reasoning_tokens
            usage.total_tokens -= streamed.attempt_usage.total_tokens
            streamed.attempt_usage = UsageTotals()
            streamed.saw_usage = False
            streamed.budget_tokens = streamed.estimated_message_tokens
        await emit(
            "model_retry_scheduled",
            {
                "turn": turn,
                "retry_after": event.retry_after or 0.0,
                "attempt": event.retry_attempt or 1,
                "reason": event.retry_reason or "rate_limit",
                "resets_stream": event.retry_resets_stream,
            },
        )
    elif event.type == "usage":
        streamed.saw_usage = True
        usage.prompt_tokens += event.prompt_tokens or 0
        usage.completion_tokens += event.completion_tokens or 0
        usage.reasoning_tokens += event.reasoning_tokens or 0
        usage.total_tokens += event.total_tokens or 0
        streamed.attempt_usage.prompt_tokens += event.prompt_tokens or 0
        streamed.attempt_usage.completion_tokens += event.completion_tokens or 0
        streamed.attempt_usage.reasoning_tokens += event.reasoning_tokens or 0
        streamed.attempt_usage.total_tokens += event.total_tokens or 0
        streamed.budget_tokens = event.prompt_tokens or usage.total_tokens
        await emit(
            "usage",
            {
                "turn": turn,
                "prompt_tokens": event.prompt_tokens or 0,
                "completion_tokens": event.completion_tokens or 0,
                "reasoning_tokens": event.reasoning_tokens or 0,
                "total_tokens": event.total_tokens or 0,
                "cumulative_tokens": usage.total_tokens,
                "estimated": False,
            },
        )


async def _emit_estimated_usage(
    runner: Any,
    messages: List[Message],
    *,
    turn: int,
    usage: UsageTotals,
    streamed: StreamedTurn,
) -> None:
    prompt_tokens = estimate_prompt_tokens(messages)
    tool_arguments_json = "".join(
        pending.arguments_json for pending in streamed.pending_calls.values()
    )
    completion_tokens = estimate_completion_tokens(
        streamed.assistant_text,
        tool_arguments_json=tool_arguments_json,
    )
    total_tokens = prompt_tokens + completion_tokens
    usage.prompt_tokens += prompt_tokens
    usage.completion_tokens += completion_tokens
    usage.total_tokens += total_tokens
    streamed.budget_tokens = prompt_tokens
    await runner.emit(
        "usage",
        {
            "turn": turn,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cumulative_tokens": usage.total_tokens,
            "estimated": True,
        },
    )


async def iter_provider_events(
    runner: Any,
    messages: List[Message],
) -> AsyncIterator[StreamEvent]:
    stream_options: Dict[str, Any] = {}
    if runner.reasoning_effort is not None:
        stream_options["reasoning_effort"] = runner.reasoning_effort
    agen = runner.registry.stream(
        runner.model_id,
        messages_for_model(
            messages,
            keep_recent=runner.tool_result_keep_recent,
            prune_tokens=runner.tool_result_prune_tokens,
        ),
        runner.tool_schemas,
        **stream_options,
    )
    try:
        while True:
            runner._raise_if_runtime_exceeded()
            timeout = runner._remaining_runtime()
            try:
                if timeout is None:
                    event = await agen.__anext__()
                else:
                    event = await asyncio.wait_for(
                        agen.__anext__(),
                        timeout=max(timeout, 0.0),
                    )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise runner._runtime_exceeded_error() from None
            yield event
    finally:
        try:
            await agen.aclose()
        except RuntimeError:
            pass



def tool_is_parallel(runner: Any, tool_call: ToolCall) -> bool:
    tool = runner.tools.get(tool_call.name)
    return bool(getattr(tool, "parallel", False))


def build_tool_calls(
    pending_calls: Dict[int, PendingToolCall],
) -> List[ToolCall]:
    tool_calls: List[ToolCall] = []
    for pending in pending_calls.values():
        decode_error: Optional[str] = None
        arguments: Dict[str, Any] = {}
        raw = pending.arguments_json.strip()
        if raw:
            try:
                decoded = json.loads(pending.arguments_json)
            except json.JSONDecodeError as exc:
                decode_error = f"Invalid tool arguments: {pending.arguments_json} ({exc})"
                decoded = {}
            if decode_error is None and not isinstance(decoded, dict):
                decode_error = "Tool arguments must decode to a JSON object."
                decoded = {}
            arguments = decoded if isinstance(decoded, dict) else {}
        call = ToolCall(
            id=pending.id,
            name=pending.name or "unknown_tool",
            arguments=arguments,
            metadata=dict(pending.metadata),
        )
        if decode_error:
            call.result_status = "error"
            call.arguments["_decode_error"] = decode_error
        tool_calls.append(call)
    return tool_calls


async def run_tool_calls(
    runner: Any,
    messages: List[Message],
    tool_calls: List[ToolCall],
) -> None:
    limit_error: Optional[HarnessLimitExceeded] = None

    async def run_one(tool_call: ToolCall) -> ToolResult:
        nonlocal limit_error
        if limit_error is not None:
            result = ToolResult(
                status="error",
                content=f"max_tool_calls={runner.max_tool_calls} exceeded",
                error_type="HarnessLimitExceeded",
            )
            await emit_tool_result(runner, tool_call, result)
        elif (
            runner.max_tool_calls is not None
            and runner.tool_calls_so_far >= runner.max_tool_calls
        ):
            result = ToolResult(
                status="error",
                content=f"max_tool_calls={runner.max_tool_calls} exceeded",
                error_type="HarnessLimitExceeded",
            )
            limit_error = HarnessLimitExceeded(
                "max_tool_calls",
                float(runner.tool_calls_so_far + 1),
                float(runner.max_tool_calls),
                f"Harness exceeded max_tool_calls={runner.max_tool_calls}",
            )
            await emit_tool_result(runner, tool_call, result)
        else:
            result = await execute_tool(runner, tool_call)
            runner.tool_calls_so_far += 1
            if (
                result.status == "timeout"
                and runner.deadline is not None
                and time.monotonic() >= runner.deadline
            ):
                limit_error = runner._runtime_exceeded_error()
        tool_call.result_status = result.status
        return result

    async def commit(tool_call: ToolCall, result: ToolResult) -> None:
        bounded = limit_tool_output(runner, result.for_model())
        runner.state.add_tool_message(messages, tool_call, bounded)
        notify = getattr(runner, "notify_addons", None)
        if notify is not None:
            await notify("on_tool", tool_call=tool_call, result=result)

    index = 0
    while index < len(tool_calls):
        if tool_is_parallel(runner, tool_calls[index]):
            batch: List[ToolCall] = []
            while index < len(tool_calls) and tool_is_parallel(runner, tool_calls[index]):
                batch.append(tool_calls[index])
                index += 1
            for offset in range(0, len(batch), runner.max_parallel_tool_calls):
                chunk = batch[offset : offset + runner.max_parallel_tool_calls]
                results = await asyncio.gather(*[run_one(call) for call in chunk])
                for call, result in zip(chunk, results):
                    await commit(call, result)
        else:
            call = tool_calls[index]
            result = await run_one(call)
            await commit(call, result)
            index += 1

    if limit_error is not None:
        raise limit_error


async def emit_tool_result(
    runner: Any,
    tool_call: ToolCall,
    result: ToolResult,
) -> None:
    bounded = limit_tool_output(runner, result.for_model())
    await runner.emit(
        "tool_execution_started",
        {
            "tool_call_id": tool_call.id,
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    )
    await runner.emit(
        "tool_execution_completed",
        tool_completed_payload(tool_call, result, bounded),
    )


async def execute_tool(runner: Any, tool_call: ToolCall) -> ToolResult:
    decode_error = tool_call.arguments.pop("_decode_error", None)
    if decode_error:
        result = ToolResult(status="error", content=str(decode_error), error_type="ValueError")
        await emit_tool_result(runner, tool_call, result)
        return result
    if tool_call.name not in runner.tools:
        result = ToolResult(
            status="error",
            content=f"Tool '{tool_call.name}' is not registered.",
            error_type="KeyError",
        )
        await emit_tool_result(runner, tool_call, result)
        return result

    denied = await runner.notify_addons(
        "before_tool",
        tool_name=tool_call.name,
        arguments=dict(tool_call.arguments),
        tool_call=tool_call,
        emit=runner.emit,
        sink=runner.sink,
    )
    if denied:
        result = ToolResult(
            status="error",
            content=str(denied),
            error_type="PermissionError",
        )
        await emit_tool_result(runner, tool_call, result)
        return result

    await runner.emit(
        "tool_execution_started",
        {
            "tool_call_id": tool_call.id,
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    )
    result = await invoke_tool(runner, tool_call)
    bounded = limit_tool_output(runner, result.for_model())
    await runner.emit(
        "tool_execution_completed",
        tool_completed_payload(tool_call, result, bounded),
    )
    return result


async def invoke_tool(runner: Any, tool_call: ToolCall) -> ToolResult:
    token = current_tool_call_id.set(tool_call.id)
    try:
        execute = runner.tools[tool_call.name].execute(
            sink=runner.sink,
            args=tool_call.arguments,
        )
        timeout = runner._remaining_runtime()
        if timeout is None:
            raw = await execute
        else:
            raw = await asyncio.wait_for(execute, timeout=max(timeout, 0.0))
        return ToolResult(status="success", content=coerce_tool_output(raw))
    except asyncio.TimeoutError:
        return ToolResult(
            status="timeout",
            content="tool execution exceeded remaining run time",
            error_type="TimeoutError",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ToolResult(
            status="error",
            content=str(exc) or type(exc).__name__,
            error_type=type(exc).__name__,
        )
    finally:
        current_tool_call_id.reset(token)


def tool_completed_payload(
    tool_call: ToolCall,
    result: ToolResult,
    bounded: Content,
) -> Dict[str, Any]:
    original = result.for_model()
    if isinstance(original, str):
        original_preview = original
        original_chars = len(original)
    else:
        original_preview = text_from_content(original)
        original_chars = len(original_preview)
    preview = bounded if isinstance(bounded, str) else text_from_content(bounded)
    return {
        "tool_call_id": tool_call.id,
        "tool_name": tool_call.name,
        "status": result.status,
        "result": preview,
        "truncated": preview != original_preview,
        "original_chars": original_chars,
    }


def limit_tool_output(runner: Any, value: Content) -> Content:
    if isinstance(value, list):
        return [
            (
                {
                    **part,
                    "text": limit_text(runner, str(part.get("text") or "")),
                }
                if isinstance(part, dict) and part.get("type") == "text"
                else part
            )
            for part in value
        ]
    return limit_text(runner, value)


def limit_text(runner: Any, value: str) -> str:
    return bound_tool_result(value, max_chars=runner.tool_result_max_chars)


def coerce_tool_output(value: Any) -> Content:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return value
    try:
        return json.dumps(value)
    except TypeError:
        return str(value)


def _clear_cancellation() -> None:
    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


async def run_session(
    harness: "CoreHarness",
    user_input: Content,
    *,
    conversation: Optional[List[Message]] = None,
    session_id: Optional[str] = None,
) -> HarnessResult:
    """Run turns until the model stops calling tools or a limit is hit."""
    active_session = session_id or harness.session_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    started_at = time.monotonic()
    harness._set_active_identity(run_id, active_session)
    messages = await harness._initial_messages(
        active_session,
        user_input,
        conversation,
    )
    await harness.emit(
        "run_started",
        {
            "model_id": harness.model_id,
            "tool_names": list(harness.tools),
            "prompt": text_from_content(user_input),
        },
    )
    await harness.notify_addons(
        "before_run",
        messages=messages,
        emit=harness.emit,
    )
    await harness._persist_conversation(active_session, messages)

    usage = UsageTotals()
    all_tool_calls: List[ToolCall] = []
    context_limit = harness.state.context_limit(harness.model_id)
    context_left: Optional[int] = None
    turn = 0
    deadline = None
    if harness.limits.max_runtime_seconds is not None:
        deadline = started_at + harness.limits.max_runtime_seconds
    from core_harness.turn_runner import TurnRunner

    turn_runner = TurnRunner(
        registry=harness.registry,
        model_id=harness.model_id,
        reasoning_effort=harness.reasoning_effort,
        tool_schemas=harness.tool_schemas(),
        tools=harness.tools,
        sink=harness.sink,
        emit=harness.emit,
        state=harness.state,
        context_limit=context_limit,
        tool_result_max_chars=harness.tool_result_max_chars,
        tool_result_keep_recent=harness.tool_result_keep_recent,
        tool_result_prune_tokens=harness.tool_result_prune_tokens,
        context_target_tokens=harness.context_target_tokens,
        max_tool_calls=harness.limits.max_tool_calls,
        deadline=deadline,
        max_runtime_seconds=harness.limits.max_runtime_seconds,
        max_parallel_tool_calls=harness.config.max_parallel_tool_calls,
        notify_addons=harness.notify_addons,
    )

    try:
        for turn in range(harness.max_turns):
            _raise_if_limit(harness, "max_runtime_seconds", time.monotonic() - started_at)
            _raise_if_limit(harness, "max_tokens", usage.total_tokens)
            remaining = None
            if deadline is not None:
                remaining = max(deadline - time.monotonic(), 0.0)
            turn_runner.remaining_runtime = remaining
            turn_runner.deadline = deadline
            await _deliver_child_results(harness, messages, turn)
            await harness.notify_addons("before_turn", turn=turn, messages=messages)
            result = await turn_runner.run(
                messages,
                turn=turn,
                usage=usage,
                context_left=context_left,
            )
            await harness.notify_addons(
                "after_turn",
                turn=turn,
                messages=messages,
                had_tool_calls=bool(result.tool_calls),
            )
            context_left = result.context_left
            all_tool_calls.extend(result.tool_calls)
            _raise_if_limit(harness, "max_tool_calls", len(all_tool_calls))
            _raise_if_limit(harness, "max_tokens", usage.total_tokens)

            if not result.tool_calls:
                children = [record.child_id for record in harness.child_tasks.values()
                            if record.task is not None and not record.task.done()]
                if children or harness._child_results:
                    if children and not harness._child_results:
                        await harness.emit("waiting_for_children", {"turn": turn, "child_ids": children})
                        await wait_for_child_result(
                            harness,
                            None if deadline is None else max(0.0, deadline - time.monotonic()),
                        )
                    _raise_if_limit(harness, "max_runtime_seconds", time.monotonic() - started_at)
                    await _deliver_child_results(harness, messages, turn)
                    await harness._persist_state(
                        session_id=active_session, turn=turn, messages=messages,
                        usage=usage, context_limit=context_limit, context_left=context_left,
                        status="running", metadata={"run_id": run_id},
                    )
                    continue
                await harness._persist_state(
                    session_id=active_session,
                    turn=turn,
                    messages=messages,
                    usage=usage,
                    context_limit=context_limit,
                    context_left=context_left,
                    status="completed",
                    metadata={"output_text": result.assistant_text, "run_id": run_id},
                )
                await harness.emit(
                    "run_completed",
                    {
                        "turn": turn,
                        "output_text": result.assistant_text,
                        "usage": usage.model_dump(),
                        "context": {
                            "context_limit": context_limit,
                            "tokens_used": result.budget_tokens,
                            "context_left": context_left,
                            "utilization": (
                                result.budget_tokens / context_limit
                                if context_limit
                                else None
                            ),
                            "message_sizes": result.message_sizes,
                        },
                    },
                )
                completed = HarnessResult(
                    output_text=result.assistant_text,
                    messages=messages,
                    tool_calls=all_tool_calls,
                    usage=usage,
                    context_limit=context_limit,
                    context_left=context_left,
                )
                try:
                    await harness.notify_addons(
                        "after_run",
                        task=text_from_content(user_input),
                        result=completed,
                        messages=messages,
                        emit=harness.emit,
                    )
                except Exception:
                    logger.exception("after_run addon failed; completed run is unaffected")
                return completed

            await harness._persist_state(
                session_id=active_session,
                turn=turn,
                messages=messages,
                usage=usage,
                context_limit=context_limit,
                context_left=context_left,
                status="running",
                metadata={"run_id": run_id},
            )
        _exceed(
            "max_turns",
            float(harness.max_turns),
            float(harness.max_turns),
            f"Harness exceeded max_turns={harness.max_turns}",
        )
    except asyncio.CancelledError:
        _clear_cancellation()
        await harness.shutdown_children()
        await harness.emit("run_cancelled", {"turn": turn, "reason": "cancelled"})
        await harness._persist_state(
            session_id=active_session, turn=turn, messages=messages, usage=usage,
            context_limit=context_limit, context_left=context_left,
            status="cancelled", metadata={"reason": "cancelled", "run_id": run_id},
        )
        raise HarnessCancelled("cancelled") from None
    except HarnessCancelled as exc:
        await harness.shutdown_children()
        await harness.emit("run_cancelled", {"turn": turn, "reason": str(exc)})
        await harness._persist_state(
            session_id=active_session,
            turn=turn,
            messages=messages,
            usage=usage,
            context_limit=context_limit,
            context_left=context_left,
            status="cancelled",
            metadata={"reason": str(exc), "run_id": run_id},
        )
        raise
    except HarnessLimitExceeded as exc:
        await harness.shutdown_children()
        await harness.emit(
            "run_limit_exceeded",
            {
                "turn": turn,
                "limit": exc.limit,
                "value": exc.value,
                "max": exc.maximum,
                "message": str(exc),
            },
        )
        await harness._persist_state(
            session_id=active_session,
            turn=turn,
            messages=messages,
            usage=usage,
            context_limit=context_limit,
            context_left=context_left,
            status="failed",
            metadata={
                "limit": exc.limit,
                "message": str(exc),
                "run_id": run_id,
            },
        )
        raise
    except Exception as exc:
        await harness.shutdown_children()
        await harness.emit(
            "run_failed",
            {
                "turn": turn,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        await harness._persist_state(
            session_id=active_session,
            turn=turn,
            messages=messages,
            usage=usage,
            context_limit=context_limit,
            context_left=context_left,
            status="failed",
            metadata={"error_type": type(exc).__name__, "message": str(exc), "run_id": run_id},
        )
        raise


async def _deliver_child_results(harness: "CoreHarness", messages: List[Message], turn: int) -> None:
    for message in harness.drain_child_results():
        messages.append(message)
        await harness.emit("message_injected", {
            "turn": turn, "role": message.role, "content": message.content, "source": "subagent",
        })


def _raise_if_limit(harness: "CoreHarness", name: str, value: float) -> None:
    maximum = getattr(harness.limits, name)
    if maximum is None:
        return
    if value > maximum or (name == "max_runtime_seconds" and value >= maximum):
        _exceed(name, value, float(maximum), f"Harness exceeded {name}={maximum}")


def _exceed(limit: str, value: float, maximum: float, message: str) -> None:
    raise HarnessLimitExceeded(limit, value, maximum, message)


__all__ = ["TurnResult", "run_session"]
