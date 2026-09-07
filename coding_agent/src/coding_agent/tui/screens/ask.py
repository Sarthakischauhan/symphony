"""Ask-user question and approval flow mixed into CodingAgentApp."""

from __future__ import annotations

from typing import Any, Mapping

from coding_agent.tui.composer.input import PromptInput
from coding_agent.tui.composer.slash_menu import SlashMenu


class QuestionSurface:
    """Ask-user composer flow mixed into CodingAgentApp."""

    def _show_question(self, payload: Mapping[str, Any]) -> None:
        request_id = str(payload.get("request_id") or "")
        question = str(payload.get("question") or "")
        choices = [str(choice) for choice in payload.get("choices") or []]
        default = str(payload.get("default") or "")
        kind = str(payload.get("kind") or "")
        if not request_id or not question:
            self.add_notice("The agent sent an invalid question request.", "error")
            return
        self._pending_question_id = request_id
        self._pending_question_agent_id = str(payload.get("agent_id") or "") if payload.get("parent_id") else ""
        self._pending_question_default = default
        self._ui_state.phase = "paused"
        self._ui_state.detail = "waiting for user"
        self._update_composer_hint()
        menu = self.query_one(
            "#approval-menu" if kind == "approval" else "#slash-menu",
            SlashMenu,
        )
        menu.set_question(
            question,
            choices,
            default=default,
            kind=kind,
        )
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = kind == "approval"
        prompt.disabled = False
        prompt.value = "" if choices else default
        prompt.cursor_position = len(prompt.value)
        prompt.focus()

    async def _answer_question(self, answer: str) -> None:
        request_id = self._pending_question_id
        if request_id is None:
            return
        self._pending_question_id = None
        self._pending_question_agent_id = ""
        self._pending_question_default = ""
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        self.query_one("#approval-menu", SlashMenu).set_commands(())
        await self.sink.answer_user(request_id, answer)
        self._ui_state.phase = "thinking" if self._busy else "idle"
        self._ui_state.detail = "resuming" if self._busy else "ready"
        prompt = self.query_one("#prompt", PromptInput)
        prompt.submit_on_enter = False
        prompt.disabled = self._busy
        self._update_composer_hint()
