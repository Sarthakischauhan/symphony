"""Browser-use loop.

Jev (an evaluation model) sees the element table and returns one operation
plus speculative targets. This module executes only the matching target and
emits the same control-plane events as every other Symphony product.

The chat harness loop is intentionally not the policy. Jev cannot emit free
tool arguments, and pretending that an empty ``{}`` tool call chose an
element would hide the decision. ``CoreHarness.emit`` still stamps run
identity so a TUI or ``core-server`` can render the trace.
"""

from __future__ import annotations

from typing import Any, Optional

from core_ai.registry import ModelRegistry
from core_harness import ControlPlaneEventType, CoreHarness, EventSink, HarnessConfig

from browser_agent.models import BrowserRunResult, Decision, StepRecord
from browser_agent.policy import Policy, candidates_for
from browser_agent.session import PageSession
from browser_agent.text import TextUnavailable, TextWriter, redact_typed

_MIN_CONFIDENCE = 0.25


class BrowserAgent:
    def __init__(
        self,
        policy: Policy,
        *,
        max_steps: int = 8,
        min_confidence: float = _MIN_CONFIDENCE,
        text_writer: Optional[TextWriter] = None,
        sink: Optional[EventSink] = None,
        goal_met_stop: float = 0.92,
    ) -> None:
        self.policy = policy
        self.max_steps = max_steps
        self.min_confidence = min_confidence
        self.text_writer = text_writer
        self.sink = sink or EventSink()
        self.goal_met_stop = goal_met_stop
        self.harness = CoreHarness(
            registry=ModelRegistry(),
            model_id=f"{policy.provider}:{policy.name}",
            system_prompt=(
                "You are the Symphony browser-use agent. Jev, an evaluation "
                "model, chooses every browser operation and element. A text "
                "model is used only to write a string that must be typed."
            ),
            config=HarnessConfig(max_turns=max_steps),
            sink=self.sink,
            agent_id="browser",
        )

    async def run(self, goal: str, session: PageSession) -> BrowserRunResult:
        history: list[dict[str, Any]] = []
        steps: list[StepRecord] = []
        candidates = candidates_for(goal)
        status = "limited"
        output = ""
        message = ""
        last_url = ""
        last_title = ""
        await self.harness.emit(
            ControlPlaneEventType.RUN_STARTED,
            {
                "goal": goal,
                "model": self.policy.name,
                "provider": self.policy.provider,
                "agent": "browser",
                "max_steps": self.max_steps,
            },
        )
        try:
            for step_index in range(1, self.max_steps + 1):
                observation = await session.observe()
                last_url = observation.url
                last_title = observation.title
                await self.harness.emit(
                    ControlPlaneEventType.TURN_STARTED,
                    {"turn": step_index, "url": observation.url, "title": observation.title},
                )
                decision = await self.policy.choose(
                    goal=goal,
                    observation=observation,
                    history=history,
                    candidates=candidates,
                )
                decision = self._break_loop(decision, history)
                if self._should_stop(decision):
                    decision = decision.model_copy(
                        update={"operation": "DONE", "reason": decision.reason or "Goal is visible."}
                    )
                typed = await self._resolve_text(decision, goal, observation)
                typed_for_page = typed if decision.operation == "TYPE_TEXT" else ""
                if decision.operation == "TYPE_TEXT":
                    field = observation.find(decision.type_target)
                    decision = decision.model_copy(
                        update={"type_value": redact_typed(field, typed)}
                    )
                await self.harness.emit(
                    ControlPlaneEventType.JEV_DECISION,
                    decision.event_payload() | {"turn": step_index},
                )
                note = decision.reason or _narrate(decision)
                await self.harness.emit(
                    ControlPlaneEventType.TEXT_DELTA,
                    {"turn": step_index, "delta": note},
                )
                if decision.operation in {"DONE", "BLOCKED"} or (
                    decision.operation not in {"WAIT", "SCROLL_DOWN", "SCROLL_UP"}
                    and decision.confidence < self.min_confidence
                ):
                    status = "done" if decision.operation == "DONE" else "blocked"
                    output = observation.text
                    message = decision.reason or (
                        "Stopped because the chosen action was below the confidence floor."
                        if decision.confidence < self.min_confidence
                        and decision.operation not in {"DONE", "BLOCKED"}
                        else ""
                    )
                    steps.append(
                        StepRecord(
                            step=step_index,
                            operation=decision.operation if status == "done" else "BLOCKED",
                            confidence=decision.confidence,
                            url=observation.url,
                            note=message or note,
                        )
                    )
                    await self.harness.emit(
                        ControlPlaneEventType.TURN_COMPLETED,
                        {"turn": step_index, "operation": decision.operation},
                    )
                    break
                if decision.operation == "TYPE_TEXT" and not typed_for_page:
                    status = "blocked"
                    message = "TYPE_TEXT was chosen but no string was available."
                    output = observation.text
                    steps.append(
                        StepRecord(
                            step=step_index,
                            operation="BLOCKED",
                            confidence=decision.confidence,
                            url=observation.url,
                            note=message,
                        )
                    )
                    break
                await self.harness.emit(
                    ControlPlaneEventType.TOOL_EXECUTION_STARTED,
                    {
                        "name": decision.operation.lower(),
                        "turn": step_index,
                        "target": decision.target_index(),
                    },
                )
                await session.act(
                    decision,
                    typed_for_page if decision.operation == "TYPE_TEXT" else "",
                )
                await self.harness.emit(
                    ControlPlaneEventType.TOOL_EXECUTION_COMPLETED,
                    {"name": decision.operation.lower(), "turn": step_index, "status": "success"},
                )
                record = StepRecord(
                    step=step_index,
                    operation=decision.operation,
                    target=decision.target_index(),
                    type_value=decision.type_value if decision.operation == "TYPE_TEXT" else "",
                    confidence=decision.confidence,
                    url=observation.url,
                    note=note,
                )
                steps.append(record)
                history.append(
                    {
                        "step": step_index,
                        "operation": decision.operation,
                        "target": decision.target_index(),
                        "value": record.type_value,
                        "url": observation.url,
                    }
                )
                await self.harness.emit(
                    ControlPlaneEventType.TURN_COMPLETED,
                    {"turn": step_index, "operation": decision.operation},
                )
            else:
                status = "limited"
                message = f"Stopped after {self.max_steps} steps."
                observation = await session.observe()
                last_url = observation.url
                last_title = observation.title
                output = observation.text
                await self.harness.emit(
                    ControlPlaneEventType.RUN_LIMIT_EXCEEDED,
                    {"max_steps": self.max_steps, "message": message},
                )
        except Exception as exc:
            status = "error"
            message = str(exc)
            await self.harness.emit(
                ControlPlaneEventType.RUN_FAILED,
                {"message": message, "error_type": type(exc).__name__},
            )
            return BrowserRunResult(
                status="error",
                output_text=output,
                url=last_url,
                title=last_title,
                goal=goal,
                model=self.policy.name,
                provider=self.policy.provider,
                steps=steps,
                message=message,
            )

        result = BrowserRunResult(
            status=status,  # type: ignore[arg-type]
            output_text=output if status != "done" else (output or last_title),
            url=last_url,
            title=last_title,
            goal=goal,
            model=self.policy.name,
            provider=self.policy.provider,
            steps=steps,
            message=message,
        )
        if status == "limited":
            return result
        if status == "done":
            final = await _safe_observe(session)
            if final is not None:
                result.output_text = final.text or result.output_text
                result.url = final.url or result.url
                result.title = final.title or result.title
            await self.harness.emit(
                ControlPlaneEventType.RUN_COMPLETED,
                {
                    "status": "done",
                    "output_text": result.output_text[:2000],
                    "url": result.url,
                    "steps": len(result.steps),
                },
            )
        else:
            await self.harness.emit(
                ControlPlaneEventType.RUN_COMPLETED,
                {
                    "status": status,
                    "output_text": result.output_text[:2000],
                    "url": result.url,
                    "message": message,
                    "steps": len(result.steps),
                },
            )
        return result

    def _should_stop(self, decision: Decision) -> bool:
        if decision.operation == "DONE":
            return False
        return (
            decision.goal_met
            and decision.goal_met_confidence >= self.goal_met_stop
            and decision.operation in {"WAIT", "SCROLL_DOWN", "SCROLL_UP"}
        )

    def _break_loop(self, decision: Decision, history: list[dict[str, Any]]) -> Decision:
        signature = decision.signature()
        if decision.operation in {"DONE", "BLOCKED", "SCROLL_DOWN", "SCROLL_UP", "WAIT"}:
            return decision
        recent = history[-2:]
        if len(recent) == 2 and all(
            (item.get("operation"), item.get("target"), item.get("value")) == signature
            for item in recent
        ):
            return decision.model_copy(
                update={
                    "operation": "BLOCKED",
                    "reason": "The same action was chosen twice without the page changing.",
                    "confidence": decision.confidence,
                }
            )
        return decision

    async def _resolve_text(self, decision: Decision, goal: str, observation: Any) -> str:
        if decision.operation != "TYPE_TEXT":
            return ""
        if decision.type_value:
            return decision.type_value
        field = observation.find(decision.type_target)
        if field is None or self.text_writer is None:
            return ""
        try:
            return await self.text_writer.write(goal=goal, element=field, observation=observation)
        except TextUnavailable:
            return ""


def _narrate(decision: Decision) -> str:
    target = decision.target_index()
    where = f" [{target}]" if target is not None else ""
    extra = f" {decision.type_value!r}" if decision.operation == "TYPE_TEXT" and decision.type_value else ""
    if decision.operation == "SELECT" and decision.select_option:
        extra = f" {decision.select_option!r}"
    return f"{decision.operation}{where}{extra} ({decision.confidence:.2f})"


async def _safe_observe(session: PageSession):
    try:
        return await session.observe()
    except Exception:
        return None


__all__ = ["BrowserAgent"]
