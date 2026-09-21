"""Mark mid-run control-plane events as collected after a run finishes.

The JSONL journal is append-only, so collection never rewrites historical
entries. A later ``collected`` record points at the original ``(run_id, seq)``
and stays sticky: once tagged, an event remains collected on every later load.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# Events that belong to the work between the user message and the final
# assistant reply. Token-delta types are never persisted, so they are omitted.
COLLECTABLE_EVENT_TYPES = frozenset(
    {
        "turn_started",
        "turn_completed",
        "model_retry_scheduled",
        "tool_call_started",
        "tool_execution_started",
        "tool_execution_completed",
        "usage",
        "context",
        "context_warning",
        "compaction_started",
        "compaction_completed",
        "message_injected",
        "waiting_for_children",
        "agent_spawned",
        "agent_completed",
        "agent_failed",
    }
)

TERMINAL_EVENT_TYPES = frozenset(
    {
        "run_completed",
        "run_failed",
        "run_cancelled",
        "run_limit_exceeded",
    }
)


def is_collected(payload: Mapping[str, Any] | None) -> bool:
    """True when a payload (or a later overlay) has ``collected: true``."""
    return bool(payload and payload.get("collected") is True)


def event_key(payload: Mapping[str, Any] | None) -> tuple[str, int] | None:
    """Stable identity for a stamped harness event."""
    if not payload:
        return None
    run_id = payload.get("run_id")
    seq = payload.get("seq")
    if run_id and isinstance(seq, int):
        return (str(run_id), seq)
    return None


def is_collectable_event(event_type: str, payload: Mapping[str, Any] | None = None) -> bool:
    """True for mid-run events that the TUI folds after the final reply."""
    if event_type not in COLLECTABLE_EVENT_TYPES:
        return False
    if is_collected(payload):
        return False
    return True


def collected_keys(events: Iterable[tuple[str, Mapping[str, Any]]]) -> set[tuple[str, int]]:
    """Return every ``(run_id, seq)`` that has been tagged collected."""
    keys: set[tuple[str, int]] = set()
    for event_type, payload in events:
        key = event_key(payload)
        if key is None:
            continue
        if event_type == "collected" or is_collected(payload):
            keys.add(key)
    return keys


def apply_collection(
    events: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    collected: Iterable[tuple[str, int]] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Overlay ``collected: true`` onto events that have been tagged.

    Overlay records (``event_type == "collected"``) are consumed and not
    returned; the original event keeps its type and gains the flag.
    """
    tagged = set(collected) if collected is not None else collected_keys(events)
    applied: list[tuple[str, dict[str, Any]]] = []
    for event_type, payload in events:
        if event_type == "collected":
            continue
        outgoing = dict(payload)
        key = event_key(outgoing)
        if key is not None and key in tagged:
            outgoing["collected"] = True
        applied.append((event_type, outgoing))
    return applied


def collectable_from_events(
    events: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    run_id: str | None = None,
) -> list[tuple[str, int]]:
    """Keys of mid-run events that should be collected for a finished run.

    Collection covers events from ``run_started`` (exclusive) up to the
    terminal run event (exclusive). The user prompt and the final assistant
    output stay uncollected so the TUI can keep them as visible transcript
    rows. When ``run_id`` is omitted, the most recent terminal event's run
    is collected.
    """
    if run_id is None:
        run_id = _latest_terminal_run_id(events)
    if not run_id:
        return []
    started = False
    keys: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for event_type, payload in events:
        payload_run = str(payload.get("run_id") or "")
        if payload_run != run_id:
            continue
        if event_type == "run_started":
            started = True
            continue
        if not started:
            continue
        if event_type in TERMINAL_EVENT_TYPES:
            break
        if not is_collectable_event(event_type, payload):
            continue
        key = event_key(payload)
        if key is None or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _latest_terminal_run_id(
    events: Sequence[tuple[str, Mapping[str, Any]]],
) -> str | None:
    for event_type, payload in reversed(list(events)):
        if event_type in TERMINAL_EVENT_TYPES:
            run_id = payload.get("run_id")
            if run_id:
                return str(run_id)
    return None


__all__ = [
    "COLLECTABLE_EVENT_TYPES",
    "TERMINAL_EVENT_TYPES",
    "apply_collection",
    "collectable_from_events",
    "collected_keys",
    "event_key",
    "is_collectable_event",
    "is_collected",
]
