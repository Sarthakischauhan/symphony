"""Textual sink for harness events.

This is not a second control-plane product. It implements the harness
``EventSink`` so the UI can observe the same events ``CoreHarness``
emits. Cancel is a TUI action: it dismisses questions and cancels the
run worker. The harness does not poll this object for cancel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from textual.message import Message

from core_harness import EventSink, ControlPlaneEventType, HumanInteraction


class HarnessEvent(Message):
    """Posted onto the Textual app when the harness emits an event."""

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


class TextualInteraction(HumanInteraction):
    """The TUI's question slot. An unbound sink has nobody to ask."""

    sink: "TextualEventSink"

    async def request_user_input(self, *, default: str = "", **question: Any) -> str:
        if self.sink._app is None:
            return default
        return await super().request_user_input(default=default, **question)


class TextualEventSink(EventSink):
    """TUI adapter: post events to the app and track the TUI's cancel state."""

    interaction: TextualInteraction

    def __init__(self, *, workspace: str | Path = ".") -> None:
        super().__init__()
        self._app: Any = None
        self.workspace = Path(workspace).resolve()
        self.interaction = TextualInteraction(self)
        self._cancelled = False
        self._cancel_reason = "cancelled"
        self._cancel_parent: Optional[TextualEventSink] = None

    def bind(self, app: Any) -> None:
        self._app = app

    def fork(self) -> "TextualEventSink":
        """Child plane with the shared composer.

        The TUI has one pending-question slot and answers on the parent plane,
        so the child's interaction port is a fork of this one.
        """
        child = TextualEventSink(workspace=self.workspace)
        child.bind(self._app)
        child._cancel_parent = self
        child.interaction = self.interaction.fork(child)
        return child

    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._app is None:
            return
        # Register the waiter before posting the message.  The Textual event
        # may be handled immediately, while AskUserTool only calls
        # ``ask_user`` after ``emit`` returns.
        if event_type == "question_asked":
            request_id = str(payload.get("request_id") or "")
            if request_id:
                self.interaction.expect(request_id)
        self._app.post_message(HarnessEvent(event_type, payload))

    def request_cancel(self, reason: str = "user_cancel") -> None:
        """Dismiss pending questions. The TUI cancels the run worker."""
        self._cancelled = True
        self._cancel_reason = reason
        self.interaction.dismiss("Deny")

    @property
    def cancelled(self) -> bool:
        if self._cancelled:
            return True
        parent = self._cancel_parent
        return bool(parent is not None and parent.cancelled)

    @property
    def cancel_reason(self) -> str:
        if self._cancelled:
            return self._cancel_reason
        parent = self._cancel_parent
        if parent is not None and parent.cancelled:
            return parent.cancel_reason
        return self._cancel_reason

    def reset_cancel(self) -> None:
        self._cancelled = False
        self._cancel_reason = "cancelled"
