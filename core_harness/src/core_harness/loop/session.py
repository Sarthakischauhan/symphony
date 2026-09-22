"""Run turns until the model stops calling tools or a limit is hit."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from itertools import count
from typing import TYPE_CHECKING, List, Optional

from core_ai.content import text_from_content
from core_ai.types import Content, Message

from core_harness.addons.subagent.background import wait_for_child_result
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import HarnessResult, ToolCall, UsageTotals

if TYPE_CHECKING:
    from core_harness.harness import CoreHarness

logger = logging.getLogger(__name__)


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
        context_target_tokens=harness.context_target_tokens,
        max_tool_calls=harness.limits.max_tool_calls,
        deadline=deadline,
        max_runtime_seconds=harness.limits.max_runtime_seconds,
        max_parallel_tool_calls=harness.config.max_parallel_tool_calls,
        notify_addons=harness.notify_addons,
        session_id=active_session,
    )

    try:
        for turn in count() if harness.max_turns is None else range(harness.max_turns):
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
