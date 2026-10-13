"""Headless event sink: one log line per notable event, nothing kept in memory."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from core_harness import EventSink

LOGGED_EVENTS = frozenset(
    {
        "run_started",
        "tool_execution_started",
        "auto_decision",
        "waiting_for_children",
        "message_injected",
        "compaction_completed",
        "run_completed",
        "run_failed",
        "run_cancelled",
        "run_limit_exceeded",
    }
)
QUIET_KEYS = frozenset(
    {
        "run_id",
        "session_id",
        "seq",
        "ts",
        "schema_version",
        "parent_id",
        "started_at",
        "context",
        "usage",
    }
)


class LogLineSink(EventSink):
    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        name = event_type
        if name not in LOGGED_EVENTS:
            return
        detail = {key: value for key, value in payload.items() if key not in QUIET_KEYS}
        print(f"{time.strftime('%H:%M:%S')} {name} {json.dumps(detail, default=str)[:400]}", flush=True)
