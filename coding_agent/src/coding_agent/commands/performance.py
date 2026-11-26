"""Latest-run latency and cache counters derived from control-plane events."""

from typing import Any, Mapping

from core_harness.timing import TERMINAL_RUN_EVENTS

_TIMED_EVENTS = {
    **dict.fromkeys(TERMINAL_RUN_EVENTS, "Run"),
    "turn_completed": "Model turn",
    "tool_execution_completed": "Tool execution",
    "compaction_completed": "Compaction",
}


class RunPerformance:
    def __init__(self) -> None:
        self._session_id = ""
        self._timings: dict[str, tuple[int, float, float]] = {}
        self._cache_read = 0
        self._cache_write = 0

    def _record(self, label: str, value: Any) -> None:
        if isinstance(value, (int, float)):
            count, total, slowest = self._timings.get(label, (0, 0.0, 0.0))
            self._timings[label] = (count + 1, total + value, max(slowest, value))

    def observe(self, event: str, payload: Mapping[str, Any]) -> None:
        if payload.get("parent_id"):
            return
        if event == "run_started":
            self._session_id = str(payload.get("session_id") or "")
            self._timings.clear()
            self._cache_read = 0
            self._cache_write = 0
        elif event == "usage":
            self._cache_read += int(payload.get("cache_read_tokens") or 0)
            self._cache_write += int(payload.get("cache_write_tokens") or 0)
        else:
            label = _TIMED_EVENTS.get(event)
            if label:
                self._record(label, payload.get("duration_ms"))
            if event == "turn_completed":
                self._record("First model output", payload.get("first_output_ms"))

    def report(self, session_id: str) -> str:
        if session_id != self._session_id or not self._timings:
            return "No latency samples for this session yet."
        lines = ["Performance · latest run"]
        for label in ("Run", "First model output", "Model turn", "Tool execution", "Compaction"):
            if label in self._timings:
                count, total, slowest = self._timings[label]
                lines.append(f"{label} · {count} samples · avg {total / count:.0f} ms · max {slowest:.0f} ms")
        lines.append(f"Prompt cache · {self._cache_read:,} read · {self._cache_write:,} written")
        return "\n".join(lines)
