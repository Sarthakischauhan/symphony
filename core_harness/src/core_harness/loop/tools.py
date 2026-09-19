"""Decode, bound, and execute tool calls for one turn."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from core_ai.content import text_from_content
from core_ai.types import Content, Message

from core_harness.context import bound_tool_result
from core_harness.errors import HarnessLimitExceeded
from core_harness.models import PendingToolCall, ToolCall, ToolResult
from core_harness.tools import current_tool_call_id


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
