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

from browser_agent.gate_decision import gate, repeat_key
from browser_agent.goal_text_candidates import text_candidates
from browser_agent.jev_policy import Policy
from browser_agent.models import BrowserRunResult, Decision, Observation, RunStatus, StepRecord
from browser_agent.redact_secret_fields import redact_typed
from browser_agent.session import PageSession
from browser_agent.text_writer import TextUnavailable, TextWriter

_SYSTEM_PROMPT = (
    "You are the Symphony browser-use agent. Jev, an evaluation model, chooses every "
    "browser operation and element. A text model is used only to write a string that must be typed."
)
_TERMINAL_EVENT = {
    "done": ControlPlaneEventType.RUN_COMPLETED,
    "blocked": ControlPlaneEventType.RUN_COMPLETED,
    "limited": ControlPlaneEventType.RUN_LIMIT_EXCEEDED,
    "error": ControlPlaneEventType.RUN_FAILED,
}


class BrowserAgent:
    """Pursues one goal on one page: observe, ask the policy, gate, act, repeat."""

    def __init__(
        self,
        policy: Policy,
        *,
        max_steps: int = 8,
        min_confidence: float = 0.25,
        text_writer: Optional[TextWriter] = None,
        sink: Optional[EventSink] = None,
        goal_met_stop: float = 0.92,
    ) -> None:
        """Configure the loop. ``sink`` collects every event of every run."""
        self.policy = policy
        self.max_steps = max_steps
        self.min_confidence = min_confidence
        self.text_writer = text_writer
        self.sink = sink or EventSink()
        self.goal_met_stop = goal_met_stop

    async def run(self, goal: str, session: PageSession) -> BrowserRunResult:
        """Drive ``session`` toward ``goal`` for at most ``max_steps`` steps.

        Each run gets a fresh ``CoreHarness``, so a reused agent never shares a
        ``run_id`` or event sequence across runs. Never raises: failures end as
        ``status="error"`` with a ``run_failed`` event.
        """
        harness = CoreHarness(
            registry=ModelRegistry(),
            model_id=f"{self.policy.provider}:{self.policy.name}",
            system_prompt=_SYSTEM_PROMPT,
            config=HarnessConfig(max_turns=self.max_steps),
            sink=self.sink,
            agent_id="browser",
        )
        emit = harness.emit
        history: list[dict[str, Any]] = []
        repeat_keys: list[str] = []
        steps: list[StepRecord] = []
        candidates = text_candidates(goal)
        observation = Observation(url="")
        start = {"goal": goal, "model": self.policy.name, "provider": self.policy.provider}
        await emit(ControlPlaneEventType.RUN_STARTED, start | {"agent": "browser", "max_steps": self.max_steps})
        try:
            for step in range(1, self.max_steps + 1):
                observation = await session.observe()
                turn = {"turn": step, "url": observation.url, "title": observation.title}
                await emit(ControlPlaneEventType.TURN_STARTED, turn)
                decision = await self.policy.choose(
                    goal=goal, observation=observation, history=history, candidates=candidates
                )
                typed = await self._resolve_text(decision, goal, observation)
                decision = gate(
                    decision.model_copy(update={"type_value": typed}),
                    observation,
                    repeat_keys,
                    min_confidence=self.min_confidence,
                    goal_met_stop=self.goal_met_stop,
                )
                shown = redact_typed(observation.find(decision.type_target), decision.type_value)
                public = decision.model_copy(update={"type_value": shown})
                note = public.reason or _narrate(public)
                await emit(ControlPlaneEventType.JEV_DECISION, public.event_payload() | {"turn": step})
                await emit(ControlPlaneEventType.TEXT_DELTA, {"turn": step, "delta": note})
                record = StepRecord(
                    step=step,
                    operation=decision.operation,
                    target=decision.target_index(),
                    type_value=shown,
                    confidence=decision.confidence,
                    url=observation.url,
                    note=note,
                )
                steps.append(record)
                if decision.operation in {"DONE", "BLOCKED"}:
                    await emit(ControlPlaneEventType.TURN_COMPLETED, {"turn": step, "operation": decision.operation})
                    status: RunStatus = "done" if decision.operation == "DONE" else "blocked"
                    return await self._finish(harness, status, public.reason, observation, goal, steps)
                tool = {"name": decision.operation.lower(), "turn": step}
                await emit(ControlPlaneEventType.TOOL_EXECUTION_STARTED, tool | {"target": record.target})
                await session.act(decision)
                await emit(ControlPlaneEventType.TOOL_EXECUTION_COMPLETED, tool | {"status": "success"})
                # The repeat digest stays run-local: Jev knows everything in it
                # except the typed text, so sending it would let a PIN be brute-forced.
                repeat_keys.append(repeat_key(decision, observation))
                history.append(record.model_dump(include={"step", "operation", "target", "url"}) | {"value": shown})
                await emit(ControlPlaneEventType.TURN_COMPLETED, {"turn": step, "operation": decision.operation})
            observation = await session.observe()
            message = f"Stopped after {self.max_steps} steps."
            return await self._finish(harness, "limited", message, observation, goal, steps)
        # Run boundary: a page, network, or model failure must end the run as
        # status="error" with a run_failed event, not escape into the caller's
        # event stream half-finished.
        except Exception as exc:
            error = {"error_type": type(exc).__name__}
            return await self._finish(harness, "error", str(exc), observation, goal, steps, error)

    async def _finish(
        self,
        harness: CoreHarness,
        status: RunStatus,
        message: str,
        observation: Observation,
        goal: str,
        steps: list[StepRecord],
        extra: Optional[dict[str, Any]] = None,
    ) -> BrowserRunResult:
        """Build the result from the last observation and emit the one terminal event."""
        result = BrowserRunResult(
            status=status,
            output_text=observation.text or (observation.title if status == "done" else ""),
            url=observation.url,
            title=observation.title,
            goal=goal,
            model=self.policy.name,
            provider=self.policy.provider,
            steps=steps,
            message=message,
        )
        payload = {"status": status, "message": message, "output_text": result.output_text[:2000]}
        payload |= {"url": result.url, "steps": len(steps), "max_steps": self.max_steps, **(extra or {})}
        await harness.emit(_TERMINAL_EVENT[status], payload)
        return result

    async def _resolve_text(self, decision: Decision, goal: str, observation: Observation) -> str:
        """The string to type: Jev's chosen literal, else the text writer's, else ""."""
        if decision.operation != "TYPE_TEXT":
            return ""
        field = observation.find(decision.type_target)
        if decision.type_value or field is None or self.text_writer is None:
            return decision.type_value
        try:
            return await self.text_writer.write(goal=goal, element=field, observation=observation)
        except TextUnavailable:
            return ""


def _narrate(decision: Decision) -> str:
    """Short human note for a step without a reason, e.g. ``CLICK [2] (0.91)``."""
    target = decision.target_index()
    where = f" [{target}]" if target is not None else ""
    extra = f" {decision.type_value!r}" if decision.operation == "TYPE_TEXT" and decision.type_value else ""
    if decision.operation == "SELECT" and decision.select_option:
        extra = f" {decision.select_option!r}"
    return f"{decision.operation}{where}{extra} ({decision.confidence:.2f})"


__all__ = ["BrowserAgent"]
