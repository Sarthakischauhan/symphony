"""Activity metadata the model attaches to tool calls.

Each call may carry ``activity.verb`` / ``reason`` / ``group``. They are
stripped from the arguments before display and kept on the card and its
snapshot. Grouping no longer keys on them: folds count kinds of work instead
(see ``kinds``).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any, Mapping


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


def explored_count_label(*, tool_count: int, thought_count: int) -> str:
    parts: list[str] = []
    if tool_count:
        noun = "tool" if tool_count == 1 else "tools"
        parts.append(f"{tool_count} {noun}")
    if thought_count:
        parts.append(f"{thought_count} thought{'s' if thought_count != 1 else ''}")
    return " · ".join(parts) or "0 tools"


COMPLETION_VERBS = (
    "Stargazed",
    "Cooked",
    "Pondered",
    "Noodled",
    "Wandered",
    "Tinkered",
    "Mused",
    "Orbited",
    "Whisked",
    "Grooved",
    "Spelunked",
    "Percolated",
    "Ruminated",
    "Concocted",
    "Meandered",
    "Incubated",
    "Harmonized",
    "Forged",
    "Sketched",
    "Vibed",
)


def choose_completion_verb() -> str:
    """Pick a Claude-style verb for the completed-run collection."""
    return random.choice(COMPLETION_VERBS)


def _activity_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
