"""Wall-clock and duration stamps for control-plane event payloads.

Loop sites call these helpers when emitting so stamps are trustworthy on the
wire. Surfaces should prefer ``duration_ms`` over reconstructing elapsed time
from client clocks.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping, MutableMapping, Optional

TERMINAL_RUN_EVENTS = frozenset(
    {
        "run_completed",
        "run_cancelled",
        "run_limit_exceeded",
        "run_failed",
    }
)

# Events that close a timed span and must carry ended_at + duration_ms.
SPAN_END_EVENTS = TERMINAL_RUN_EVENTS | frozenset(
    {
        "turn_completed",
        "tool_execution_completed",
        "tool_execution_failed",
        "run_summary",
    }
)


def wall_now() -> float:
    return time.time()


def mono_now() -> float:
    return time.monotonic()


def duration_ms(started_mono: float, ended_mono: Optional[float] = None) -> int:
    end = mono_now() if ended_mono is None else ended_mono
    return max(0, int(round((end - started_mono) * 1000.0)))


def duration_human(ms: int) -> str:
    """Compact human duration for optional payload field ``duration_human``."""
    total_seconds = max(0, int(ms // 1000))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    if ms < 1000 and ms > 0:
        return f"{ms}ms"
    return f"{seconds}s"


def started_stamp(*, at: Optional[float] = None) -> Dict[str, float]:
    return {"started_at": wall_now() if at is None else float(at)}


def ended_stamp(
    started_mono: float,
    *,
    ended_mono: Optional[float] = None,
    ended_at: Optional[float] = None,
    include_human: bool = True,
) -> Dict[str, Any]:
    """Build ended_at + duration_ms (+ optional duration_human) from a mono start."""
    end_mono = mono_now() if ended_mono is None else ended_mono
    ms = duration_ms(started_mono, end_mono)
    payload: Dict[str, Any] = {
        "ended_at": wall_now() if ended_at is None else float(ended_at),
        "duration_ms": ms,
    }
    if include_human:
        payload["duration_human"] = duration_human(ms)
    return payload


def with_started(payload: Optional[Mapping[str, Any]] = None, *, at: Optional[float] = None) -> Dict[str, Any]:
    out = dict(payload or {})
    out.setdefault("started_at", wall_now() if at is None else float(at))
    return out


def with_ended(
    payload: Optional[Mapping[str, Any]],
    started_mono: float,
    *,
    ended_mono: Optional[float] = None,
    include_human: bool = True,
) -> Dict[str, Any]:
    out = dict(payload or {})
    stamp = ended_stamp(
        started_mono,
        ended_mono=ended_mono,
        include_human=include_human,
    )
    for key, value in stamp.items():
        out.setdefault(key, value)
    # Keep elapsed_seconds aligned for older consumers when duration_ms is set.
    if "elapsed_seconds" not in out and "duration_ms" in out:
        out["elapsed_seconds"] = float(out["duration_ms"]) / 1000.0
    return out


def merge_into(target: MutableMapping[str, Any], extra: Mapping[str, Any]) -> None:
    for key, value in extra.items():
        target.setdefault(key, value)


__all__ = [
    "SPAN_END_EVENTS",
    "TERMINAL_RUN_EVENTS",
    "duration_human",
    "duration_ms",
    "ended_stamp",
    "merge_into",
    "mono_now",
    "started_stamp",
    "wall_now",
    "with_ended",
    "with_started",
]
