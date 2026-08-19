"""Textual sink for the core_harness control plane.

This is not a second control-plane product. It implements the harness
``ControlPlane`` protocol so UI can observe the same events the agent already
emits through ``CoreHarness``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Union

from textual.message import Message

from core_harness import ControlCommand, ControlCommandType, ControlPlaneEventType


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
        self._question_futures: dict[str, asyncio.Future[str]] = {}
        self._cancelled = False
        self._cancel_reason = "cancelled"
        self.cancel_event = asyncio.Event()

    def bind(self, app: Any) -> None:
        self._app = app

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._app is None:
            return
        # Register the waiter before posting the message.  The Textual event
        # may be handled immediately, while AskUserTool only calls
        # ``ask_user`` after ``emit`` returns.
        event_name = (
            event_type.value
            if isinstance(event_type, ControlPlaneEventType)
            else event_type
        )
        if event_name == "question_asked":
            request_id = str((payload or {}).get("request_id") or "")
            if request_id:
                self._get_question_future(request_id)
        self._app.post_message(HarnessEvent(event_type, payload or {}))

    def request_cancel(self, reason: str = "user_cancel") -> None:
        """Synchronously stop the active run from a TUI key binding."""
        self._cancelled = True
        self._cancel_reason = reason
        self.cancel_event.set()
        for future in list(self._question_futures.values()):
            if not future.done():
                future.set_result("Deny")

    async def send_command(self, command: ControlCommand) -> None:
        if command.type == ControlCommandType.CANCEL:
            self.request_cancel(str(command.payload.get("reason", "cancelled")))

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def cancel_reason(self) -> str:
        return self._cancel_reason

    def reset_cancel(self) -> None:
        self._cancelled = False
        self._cancel_reason = "cancelled"
        self.cancel_event = asyncio.Event()

    async def ask_user(self, request_id: str) -> str:
        if self._app is None:
            return ""
        future = self._get_question_future(request_id)
        try:
            return await future
        finally:
            self._question_futures.pop(request_id, None)

    def _get_question_future(self, request_id: str) -> asyncio.Future[str]:
        future = self._question_futures.get(request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._question_futures[request_id] = future
        return future

    async def answer_user(self, request_id: str, answer: str | None) -> None:
        future = self._question_futures.get(request_id)
        if future is None or future.done():
            return
        future.set_result(answer or "")
