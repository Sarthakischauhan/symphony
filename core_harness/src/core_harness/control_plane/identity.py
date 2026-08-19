"""Stamp every control-plane emit with run identity metadata."""

from __future__ import annotations

import time
from typing import Any, Dict, Union

from core_harness.control_plane.base import ControlPlane, normalize_event_type
from core_harness.models.control_plane import EVENT_SCHEMA_VERSION, ControlPlaneEventType


class IdentifiedControlPlane:
    """Wrap an inner plane and attach run_id, session_id, seq, ts, schema_version."""

    def __init__(
        self,
        inner: ControlPlane,
        *,
        run_id: str,
        session_id: str,
        schema_version: int = EVENT_SCHEMA_VERSION,
    ) -> None:
        self.inner = inner
        self.run_id = run_id
        self.session_id = session_id
        self.schema_version = schema_version
        self._sequence = 0

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        self._sequence += 1
        stamped = {
            **(payload or {}),
            "run_id": self.run_id,
            "session_id": self.session_id,
            "seq": self._sequence,
            "ts": time.time(),
            "schema_version": self.schema_version,
        }
        await self.inner.emit(normalize_event_type(event_type), stamped)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
