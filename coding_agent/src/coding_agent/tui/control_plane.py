"""Textual sink for the core_harness control plane.

This is not a second control-plane product. It implements the harness
``ControlPlane`` protocol so UI can observe the same events the agent already
emits through ``CoreHarness``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from textual.message import Message

from core_harness import ControlPlaneEventType


class HarnessEvent(Message):
    """Posted onto the Textual app when the harness emits a control-plane event."""

    def __init__(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        super().__init__()
        if isinstance(event_type, ControlPlaneEventType):
            self.event_type = event_type.value
        else:
            self.event_type = event_type
        self.payload = payload


# Back-compat alias used by older tests / imports.
ControlPlaneEvent = HarnessEvent


class TextualControlPlane:
    """Harness ``ControlPlane`` adapter that posts events into Textual."""

    def __init__(self) -> None:
        self._app: Any = None

    def bind(self, app: Any) -> None:
        self._app = app

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._app is None:
            return
        self._app.post_message(HarnessEvent(event_type, payload or {}))
