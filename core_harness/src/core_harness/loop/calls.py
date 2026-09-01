"""Tool execution for one harness turn."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from core_ai.content import text_from_content
from core_ai.types import Content, Message

from core_harness.context import bound_tool_result
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import ToolCall, ToolResult


class TurnToolCalls:
    """Mixin: execute and persist tool calls for a turn."""

    def _tool_is_parallel(self, tool_call: ToolCall) -> bool:
        tool = self.tools.get(tool_call.name)
        return bool(getattr(tool, "parallel", False))

    async def _run_tool_calls(
        self,
        messages: List[Message],
        tool_calls: List[ToolCall],
    ) -> None:
        cancelled_rest = False
        limit_error: Optional[HarnessLimitExceeded] = None

        async def run_one(tool_call: ToolCall) -> ToolResult:
            nonlocal cancelled_rest, limit_error
            if limit_error is not None:
                result = ToolResult(
                    status="error",
                    content=f"max_tool_calls={self.max_tool_calls} exceeded",
                    error_type="HarnessLimitExceeded",
                )
                await self._emit_tool_result(tool_call, result)
            elif cancelled_rest or self._cancelled():
                result = ToolResult(status="cancelled", content=self._cancel_reason())
                cancelled_rest = True
                await self._emit_tool_result(tool_call, result)
            elif (
                self.max_tool_calls is not None
                and self.tool_calls_so_far >= self.max_tool_calls
            ):
                result = ToolResult(
                    status="error",
                    content=f"max_tool_calls={self.max_tool_calls} exceeded",
                    error_type="HarnessLimitExceeded",
                )
                limit_error = HarnessLimitExceeded(
                    "max_tool_calls",
                    float(self.tool_calls_so_far + 1),
                    float(self.max_tool_calls),
                    f"Harness exceeded max_tool_calls={self.max_tool_calls}",
                )
                await self._emit_tool_result(tool_call, result)
            else:
                result = await self._execute_tool(tool_call)
                self.tool_calls_so_far += 1
                if result.status == "cancelled":
                    cancelled_rest = True
                elif (
                    result.status == "timeout"
                    and self.deadline is not None
                    and time.monotonic() >= self.deadline
                ):
                    limit_error = self._runtime_exceeded_error()
            tool_call.result_status = result.status
            return result

        async def commit(tool_call: ToolCall, result: ToolResult) -> None:
            bounded = self._limit_tool_output(result.for_model())
            self.state.add_tool_message(messages, tool_call, bounded)

        index = 0
        while index < len(tool_calls):
            if self._tool_is_parallel(tool_calls[index]):
                batch: List[ToolCall] = []
                while index < len(tool_calls) and self._tool_is_parallel(tool_calls[index]):
                    batch.append(tool_calls[index])
                    index += 1
                for offset in range(0, len(batch), self.max_parallel_tool_calls):
                    chunk = batch[offset : offset + self.max_parallel_tool_calls]
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
        if cancelled_rest:
            raise HarnessCancelled(self._cancel_reason())


    async def _emit_tool_result(self, tool_call: ToolCall, result: ToolResult) -> None:
        bounded = self._limit_tool_output(result.for_model())
        await self.control_plane.emit(
            "tool_execution_started",
            {
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )
        await self.control_plane.emit(
            "tool_execution_completed",
            self._tool_completed_payload(tool_call, result, bounded),
        )

    async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        decode_error = tool_call.arguments.pop("_decode_error", None)
        if decode_error:
            result = ToolResult(status="error", content=str(decode_error), error_type="ValueError")
            await self._emit_tool_result(tool_call, result)
            return result
        if tool_call.name not in self.tools:
            result = ToolResult(
                status="error",
                content=f"Tool '{tool_call.name}' is not registered.",
                error_type="KeyError",
            )
            await self._emit_tool_result(tool_call, result)
            return result

        approve = getattr(self.control_plane, "approve_tool_call", None)
        if callable(approve):
            allowed = await approve(
                tool_name=tool_call.name,
                arguments=dict(tool_call.arguments),
            )
            if not allowed:
                result = ToolResult(
                    status="error",
                    content="tool call denied by user",
                    error_type="PermissionError",
                )
                await self._emit_tool_result(tool_call, result)
                return result

        await self.control_plane.emit(
            "tool_execution_started",
            {
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )
        result = await self._invoke_tool(tool_call)
        bounded = self._limit_tool_output(result.for_model())
        await self.control_plane.emit(
            "tool_execution_completed",
            self._tool_completed_payload(tool_call, result, bounded),
        )
        return result

    async def _invoke_tool(self, tool_call: ToolCall) -> ToolResult:
        execute = self.tools[tool_call.name].execute(
            control_plane=self.control_plane,
            args=tool_call.arguments,
        )
        exec_task = asyncio.create_task(execute)
        waiters = {exec_task}
        cancel_event = getattr(self.control_plane, "cancel_event", None)
        cancel_wait = None
        if cancel_event is not None and not cancel_event.is_set():
            cancel_wait = asyncio.create_task(cancel_event.wait())
            waiters.add(cancel_wait)
        timeout = self._remaining_runtime()
        try:
            done, pending = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=None if timeout is None else max(timeout, 0.0),
            )
            for task in pending:
                task.cancel()
            if not done:
                exec_task.cancel()
                return ToolResult(
                    status="timeout",
                    content="tool execution exceeded remaining run time",
                    error_type="TimeoutError",
                )
            if cancel_wait is not None and cancel_wait in done:
                exec_task.cancel()
                return ToolResult(
                    status="cancelled",
                    content=self._cancel_reason(),
                )
            try:
                raw = exec_task.result()
            except asyncio.CancelledError:
                return ToolResult(status="cancelled", content=self._cancel_reason())
            except Exception as exc:
                return ToolResult(
                    status="error",
                    content=str(exc) or type(exc).__name__,
                    error_type=type(exc).__name__,
                )
            return ToolResult(status="success", content=self._coerce_tool_output(raw))
        except Exception as exc:
            exec_task.cancel()
            return ToolResult(
                status="error",
                content=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
            )

    def _tool_completed_payload(
        self,
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

    def _limit_tool_output(self, value: Content) -> Content:
        if isinstance(value, list):
            return [
                (
                    {
                        **part,
                        "text": self._limit_text(str(part.get("text") or "")),
                    }
                    if isinstance(part, dict) and part.get("type") == "text"
                    else part
                )
                for part in value
            ]
        return self._limit_text(value)

    def _limit_text(self, value: str) -> str:
        return bound_tool_result(value, max_chars=self.tool_result_max_chars)

    def _coerce_tool_output(self, value: Any) -> Content:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return value
        try:
            return json.dumps(value)
        except TypeError:
            return str(value)
