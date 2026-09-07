"""Textual sink for harness events.

This is not a second control-plane product. It implements the harness
``EventSink`` so the UI can observe the same events ``CoreHarness``
emits. Cancel is a TUI action: it dismisses questions and cancels the
run worker. The harness does not poll this object for cancel.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Union

from textual.message import Message

from core_harness import EventSink, ControlPlaneEventType
from coding_agent.approvals import ApprovalPolicy
from coding_agent.config import ApprovalConfig, ensure_spawn_settings


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


class TextualEventSink(EventSink):
    """TUI adapter: observe events, ask the user, hold approval config."""

    def __init__(
        self,
        *,
        workspace: str | Path = ".",
        approvals: Optional[ApprovalConfig] = None,
    ) -> None:
        super().__init__()
        self._app: Any = None
        self.workspace = Path(workspace).resolve()
        self.approvals = approvals or ApprovalConfig()
        self.policy = ApprovalPolicy(self.workspace)
        self._interaction_lock = asyncio.Lock()
        self._question_futures: dict[str, asyncio.Future[str]] = {}
        self._cancelled = False
        self._cancel_reason = "cancelled"
        self._cancel_parent: Optional[TextualEventSink] = None

    def bind(self, app: Any) -> None:
        self._app = app

    def fork(self, *, approvals: Optional[ApprovalConfig] = None) -> "TextualEventSink":
        """Child plane: own approval config, shared composer.

        The TUI has one pending-question slot and answers on the parent plane.
        Sharing the interaction lock and question futures keeps child
        ``ask_user`` waiters reachable; isolating ``approvals`` is what prevents
        a sibling from flipping the parent's mode.
        """
        child = TextualEventSink(
            workspace=self.workspace,
            approvals=approvals or self.approvals.model_copy(deep=True),
        )
        child.bind(self._app)
        child._cancel_parent = self
        child._interaction_lock = self._interaction_lock
        child._question_futures = self._question_futures
        return child

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
        """Dismiss pending questions. The TUI cancels the run worker."""
        self._cancelled = True
        self._cancel_reason = reason
        for future in list(self._question_futures.values()):
            if not future.done():
                future.set_result("Deny")

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

    async def ask_user(self, request_id: str) -> str:
        if self._app is None:
            return ""
        future = self._get_question_future(request_id)
        try:
            return await future
        finally:
            self._question_futures.pop(request_id, None)

    async def request_user_input(
        self,
        *,
        question: str,
        choices: Sequence[str] = (),
        default: str = "",
        kind: str = "question",
        metadata: Optional[Dict[str, Any]] = None,
        emit: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> str:
        """Publish a question and wait for the UI answer on the same plane."""
        if self._app is None:
            return default
        async with self._interaction_lock:
            request_id = uuid.uuid4().hex
            publish = emit or self.emit
            await publish(
                "question_asked",
                {
                    "request_id": request_id,
                    "question": question,
                    "choices": list(choices),
                    "default": default,
                    "kind": kind,
                    **(metadata or {}),
                },
            )
            return await self.ask_user(request_id)

    def set_approval_mode(self, mode: str, *, persist: bool = False) -> None:
        """Change approval policy for this run and optionally persist it.

        Child planes are intentionally isolated so a child cannot silently change
        the parent's policy. An explicit user choice, however, is made in the
        shared TUI and must apply to the parent as well as future children.
        """
        self.approvals = ApprovalConfig.model_validate(
            {**self.approvals.model_dump(), "mode": mode}
        )
        parent = self._cancel_parent
        if parent is not None:
            parent.set_approval_mode(mode, persist=persist)
            return
        if persist:
            config = ensure_spawn_settings(self.workspace)
            ensure_spawn_settings(
                self.workspace,
                config=config.model_copy(update={"approvals": self.approvals}),
            )

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
