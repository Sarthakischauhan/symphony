"""Control-plane bridge that mirrors harness events into the Textual UI."""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.message import Message


class ControlPlaneEvent(Message):
    """Posted onto the Textual app when the harness emits a CP event."""

    def __init__(self, event_type: str, payload: Dict[str, Any]) -> None:
        super().__init__()
        self.event_type = event_type
        self.payload = payload


class TextualControlPlane:
    """``ControlPlane`` implementation that posts messages to a Textual app."""

    def __init__(self) -> None:
        self._app: Any = None

    def bind(self, app: Any) -> None:
        self._app = app

    async def emit(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if self._app is None:
            return
        self._app.post_message(ControlPlaneEvent(event_type, payload or {}))
