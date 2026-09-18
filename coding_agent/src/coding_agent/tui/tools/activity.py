"""Activity metadata for live tool cards and Explored folds.

Explored partitioning keys on ``activity.group``. Without a group, different
reasons still fold together via ``bool(reason)``: the reason is a label, not a
partition key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Activity:
    verb: str = ""
    reason: str = ""
    group: str = ""


_ACTIVITY_KEYS = ("activity", "verb", "reason", "goal", "group")


def parse_activity(activity: Mapping[str, Any] | str | None) -> Activity:
    """Normalize ``verb`` / ``reason`` / ``group`` from a tool activity mapping."""
    if isinstance(activity, str):
        return Activity(reason=_activity_text(activity))
    if not isinstance(activity, Mapping):
        return Activity()
    return Activity(
        verb=_activity_text(activity.get("verb")),
        reason=_activity_text(activity.get("reason") or activity.get("goal")),
        group=_activity_text(activity.get("group")),
    )


def take_activity(arguments: dict[str, Any]) -> Activity:
    """Pop UI activity from nested or flattened tool arguments and normalize it."""
    nested = arguments.pop("activity", None)
    parsed = parse_activity(nested)
    verb = parsed.verb or _activity_text(arguments.pop("verb", None))
    reason = parsed.reason or _activity_text(
        arguments.pop("reason", None) or arguments.pop("goal", None)
    )
    group = parsed.group or _activity_text(arguments.pop("group", None))
    return Activity(verb=verb, reason=reason, group=group)


def strip_activity_json(raw: str) -> str:
    """Drop nested and flattened activity fields from a raw JSON argument blob."""
    if not raw:
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return raw
    for key in _ACTIVITY_KEYS:
        parsed.pop(key, None)
    return json.dumps(parsed, separators=(",", ":"))


def same_activity_group(left: Any, right: Any) -> bool:
    """Whether two calls belong in the same Explored row.

    Group wins when either side has one. Without a group, labeled and unlabeled
    calls stay apart, but distinct reasons still fold together.
    """
    left_activity = _activity_of(left)
    right_activity = _activity_of(right)
    if left_activity.group or right_activity.group:
        return left_activity.group == right_activity.group
    return bool(left_activity.reason) == bool(right_activity.reason)


def explored_activity(calls: Sequence[Any]) -> Activity:
    """First non-empty verb/reason/group already on an Explored row."""
    verb = reason = group = ""
    for call in calls:
        activity = _activity_of(call)
        verb = verb or activity.verb
        reason = reason or activity.reason
        group = group or activity.group
        if verb and reason and group:
            break
    return Activity(verb=verb, reason=reason, group=group)


def format_explored_duration(calls: Sequence[Any]) -> str:
    """Sum snapshot durations when the row has an activity verb; else empty."""
    if not any(_activity_of(call).verb for call in calls):
        return ""
    durations = [
        duration
        for call in calls
        if (duration := getattr(call, "duration", None)) is not None
    ]
    if not durations:
        return ""
    seconds = sum(durations)
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def explored_count_label(*, tool_count: int, thought_count: int) -> str:
    parts: list[str] = []
    if tool_count:
        noun = "tool" if tool_count == 1 else "tools"
        parts.append(f"{tool_count} {noun}")
    if thought_count:
        parts.append(f"{thought_count} thought{'s' if thought_count != 1 else ''}")
    return " · ".join(parts) or "0 tools"


def explored_title(calls: Sequence[Any], *, thought_count: int = 0) -> str:
    activity = explored_activity(calls)
    title = activity.verb or activity.reason or "Explored"
    failed = sum(getattr(call, "status", "") == "failed" for call in calls)
    suffix = f" · {failed} failed" if failed else ""
    duration = format_explored_duration(calls)
    timing = f" for {duration}" if duration else ""
    return (
        f"{_clip_title(title)} · "
        f"{explored_count_label(tool_count=len(calls), thought_count=thought_count)}"
        f"{timing}{suffix}"
    )


def _clip_title(title: str) -> str:
    text = title.strip()
    if len(text) <= 96:
        return text
    return f"{text[:96].rstrip()}…"


_IRREGULAR_PAST_TENSE = {
    "build": "Built",
    "check": "Checked",
    "consider": "Considered",
    "cook": "Cooked",
    "explore": "Explored",
    "inspect": "Inspected",
    "plan": "Planned",
    "read": "Read",
    "run": "Ran",
    "search": "Searched",
    "think": "Thought",
    "write": "Wrote",
}


def past_tense_verb(verb: str, *, fallback: str = "Cooked") -> str:
    """Convert a present-participle or infinitive activity verb into past tense."""
    text = verb.strip()
    if not text:
        return fallback
    lowered = text.lower()
    stem = lowered[:-3] if lowered.endswith("ing") else lowered
    if stem in _IRREGULAR_PAST_TENSE:
        return _IRREGULAR_PAST_TENSE[stem]
    if stem.endswith("e"):
        return stem.capitalize() + "d"
    if stem.endswith("y") and len(stem) > 1 and stem[-2] not in "aeiou":
        return stem[:-1].capitalize() + "ied"
    return (stem + "ed").capitalize()


def _activity_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _activity_of(item: Any) -> Activity:
    if isinstance(item, Activity):
        return item
    return Activity(
        verb=getattr(item, "activity_verb", "") or "",
        reason=getattr(item, "activity_reason", "") or "",
        group=getattr(item, "activity_group", "") or "",
    )
