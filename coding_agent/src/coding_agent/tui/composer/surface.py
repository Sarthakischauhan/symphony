"""Slash-menu and composer-hint flow mixed into CodingAgentApp."""

from __future__ import annotations

from textual import events
from textual.widgets import OptionList, Static, TextArea

from coding_agent.credentials import OFFLINE_HINT
from coding_agent.tui.commands import (
    command_matches,
    effort_matches,
    effort_options_for_model,
    mode_matches,
    model_matches,
    model_supports_effort,
    toggle_mode,
)
from coding_agent.tui.composer.input import Composer, PromptInput, mode_label
from coding_agent.tui.composer.slash_menu import SlashMenu
from coding_agent.tui.screens.file_selector import (
    active_file_mention,
    complete_file_mention,
    file_matches,
)
from coding_agent.tui.tools.images import build_user_content
from coding_agent.tui.transcript import UserMessage


class ComposerSurface:
    """Composer submit, slash-menu navigation, and hint updates."""

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        text = event.input.expanded_value(event.input.text).strip()
        pasted_chunks = event.input.take_pasted_chunks()
        event.input.load_text("")
        if self._pending_question_id is not None:
            event.input.take_images()
            await self._answer_question(self._submitted_question_answer(text))
            return
        if not text:
            event.input.take_images()
            return
        self.query_one("#slash-menu", SlashMenu).set_commands(())
        if text.startswith("/"):
            event.input.take_images()
            await self._run_slash_command(text)
            return
        images = event.input.take_images()
        if self._agent is None:
            self.add_notice(OFFLINE_HINT, "error")
            return
        if self._busy:
            self.add_notice("A turn is already in progress.", "warning")
            return

        user_content = build_user_content(text, images)
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools = {}
        self._mount_transcript(
            UserMessage(text, pasted_chunks=pasted_chunks, images=images)
        )
        self.set_thinking("Thinking…")
        if self.mode == "plan":
            self._plan_run_active = True
        self._busy = True
        event.input.disabled = True
        self._set_status("")
        self.run_agent(user_content)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        if self._pending_question_id is not None:
            return
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        menu = (
            approval_menu
            if approval_menu.display
            else self.query_one("#slash-menu", SlashMenu)
        )
        mention = active_file_mention(event.text_area.text)
        if mention is not None:
            _start, query = mention
            menu.set_files(file_matches(self.workspace, query))
        elif event.text_area.text.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(
                model_matches(
                    event.text_area.text.removeprefix("/model "),
                    self._model_options,
                ),
                current,
            )
        elif event.text_area.text.startswith("/effort "):
            current = "default"
            efforts = ()
            if self._agent is not None:
                current = self._agent.harness.reasoning_effort or "default"
                efforts = effort_options_for_model(self._agent.harness.model_id)
            menu.set_efforts(
                effort_matches(
                    event.text_area.text.removeprefix("/effort "),
                    efforts,
                ),
                current,
            )
        elif event.text_area.text.startswith("/mode "):
            menu.set_modes(mode_matches(event.text_area.text.removeprefix("/mode ")), self.mode)
        elif event.text_area.text.startswith("/plans "):
            menu.set_plans(
                self._command_manager.plan_options(event.text_area.text.removeprefix("/plans ")),
                self._plan_store.path.name,
                command="/plans",
            )
        else:
            model_id = getattr(getattr(self._agent, "harness", None), "model_id", "")
            menu.set_commands(
                command_matches(
                    event.text_area.text,
                    include_effort=model_supports_effort(model_id),
                )
            )

    def on_key(self, event: events.Key) -> None:
        """Navigate, choose, or complete the visible slash menu."""
        prompt = self.query_one("#prompt", PromptInput)
        if not prompt.has_focus:
            return
        if event.key in {"ctrl+enter", "control+enter"}:
            prompt.action_submit()
            event.prevent_default()
            event.stop()
            return
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        menu = (
            approval_menu
            if approval_menu.display
            else self.query_one("#slash-menu", SlashMenu)
        )
        if not menu.display:
            if event.key == "tab" and not self._busy:
                toggle_mode(self)
                event.prevent_default()
                event.stop()
            return

        if event.key in {"up", "down"}:
            menu.move_selection(-1 if event.key == "up" else 1)
            event.prevent_default()
            event.stop()
            return
        if event.key in {"tab", "enter"} and menu.selected_value:
            self._choose_menu_option(menu, submit=event.key == "enter")
            event.prevent_default()
            event.stop()
        elif event.key == "enter" and self._pending_question_id is not None:
            self.call_later(prompt.action_submit)
            event.prevent_default()
            event.stop()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Apply menu choices selected with the pointer."""
        if event.option_list.id not in {"slash-menu", "approval-menu"}:
            return
        menu = event.option_list
        assert isinstance(menu, SlashMenu)
        if menu.select_option_index(event.option_index):
            self._choose_menu_option(menu, submit=True)
        event.stop()

    def _submitted_question_answer(self, text: str) -> str:
        """Prefer the visible approval highlight over empty prompt text / default."""
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        if approval_menu.display and approval_menu.selected_value:
            return approval_menu.selected_value
        return text or self._pending_question_default

    def _choose_menu_option(self, menu: SlashMenu, *, submit: bool) -> None:
        prompt = self.query_one("#prompt", PromptInput)
        if self._pending_question_id is not None and submit:
            answer = menu.selected_value
            menu.set_commands(())
            prompt.load_text("")
            self.call_later(self._answer_question, answer)
            prompt.focus()
            return
        if menu.is_file_selector:
            prompt.value, cursor = complete_file_mention(
                prompt.value,
                menu.selected_value.removeprefix("@"),
            )
            prompt.cursor_position = cursor
            menu.set_commands(())
        else:
            prompt.value = menu.selected_value
            prompt.cursor_position = len(prompt.value)
            if submit:
                menu.set_commands(())
                self.call_later(prompt.action_submit)
        prompt.focus()

    async def _run_slash_command(self, value: str) -> None:
        await self._command_manager.run(value)

    def _update_composer_hint(self) -> None:
        """Refresh the mode badge and the footer keyboard hint for the current state."""
        self.query_one("#composer", Composer).set_class(
            self.mode == "plan", "plan-mode"
        )
        self.query_one("#composer-mode", Static).update(mode_label(self.mode))
        self._set_status("")
