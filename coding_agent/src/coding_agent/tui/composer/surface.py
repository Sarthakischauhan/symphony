"""Slash-menu and composer-hint flow mixed into CodingAgentApp."""

from __future__ import annotations

from textual import events
from textual.widgets import Button, OptionList, Static, TextArea
from textual.worker import WorkerState, get_current_worker

from coding_agent.config.credentials import OFFLINE_HINT
from coding_agent.tui.chrome.footer import DEFAULT_HINT, ComposerOverlay
from coding_agent.tui.commands import (
    command_matches,
    effort_matches,
    effort_options_for_model,
    mode_matches,
    model_matches,
    model_supports_effort,
    personality_matches,
    toggle_mode,
)
from coding_agent.tui.composer.input import Composer, PromptInput, mode_label
from coding_agent.tui.composer.input import QueuedTurn
from coding_agent.tui.composer.slash_menu import SlashMenu
from coding_agent.tui.screens.file_selector import (
    active_file_mention,
    complete_file_mention,
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
            images = event.input.take_images()
            approval_menu = self.query_one("#approval-menu", SlashMenu)
            if approval_menu.display and approval_menu.selected_value:
                await self._answer_question(approval_menu.selected_value)
                if text:
                    user_content = build_user_content(text, images)
                    turn = QueuedTurn(user_content, text, pasted_chunks, images)
                    if self._busy:
                        self.queue_turn(turn)
                    else:
                        self._start_turn(turn)
                return
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
        user_content = build_user_content(text, images)
        if self._busy:
            # Do not disable the editor while the harness is working: a follow-up
            # can be prepared and submitted, then is dispatched FIFO afterward.
            self.queue_turn(QueuedTurn(user_content, text, pasted_chunks, images))
            return

        self._start_turn(QueuedTurn(user_content, text, pasted_chunks, images))

    def _start_turn(self, turn: QueuedTurn) -> None:
        self._run_generation += 1
        self.sink.reset_cancel()
        self._assistant = None
        self._thinking = None
        self._reasoning = None
        self._process = None
        self._tools = {}
        self._tool_groups = {}
        self._open_tool_group = None
        self._mount_transcript(
            UserMessage(turn.text, pasted_chunks=turn.pasted_chunks, images=turn.images)
        )
        self.set_thinking("Thinking…")
        if self.mode == "plan":
            self._plan_run_active = True
        self._busy = True
        self._set_status("")
        # The harness reads this once, on the run that is about to start.
        agent = getattr(self, "_agent", None)
        harness = getattr(agent, "harness", None)
        if harness is not None:
            harness.reply_aloud = bool(turn.voice)
        # Let the submitted message paint before checkpoint and prompt setup.
        self.call_after_refresh(self.run_agent, turn.content)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id not in {"queued-send-now", "queued-edit"} or not self._queued_turns:
            return
        prompt = self.query_one("#prompt", PromptInput)
        if event.button.id == "queued-edit":
            prompt.load_text(self.pop_queued_turn().text)
            prompt.submit_on_enter = True
            prompt.disabled = False
            prompt.focus()
            return
        if not self._busy:
            self._start_turn(self.pop_queued_turn())
            return
        # Interrupt the in-flight run and leave the prompt queued. The
        # cancelled worker starts it from ``finally`` only after the previous
        # harness call has actually returned, so two runs cannot overlap.
        self._pending_question_id = None
        self._pending_question_default = ""
        self._pending_question_agent_id = ""
        self._cancel_active_run("queued_send_now")

    def _composer_menu(self) -> SlashMenu:
        approval_menu = self.query_one("#approval-menu", SlashMenu)
        return (
            approval_menu
            if approval_menu.display
            else self.query_one("#slash-menu", SlashMenu)
        )

    def _show_file_matches(self, menu: SlashMenu, query: str) -> None:
        """Filter the last finished walk now; walk again in a worker if stale.

        The first ``@`` of a session has nothing to filter yet, so the menu
        fills when that walk lands (``_file_index_ready``).
        """
        cached = self._file_index.cached_matches(query)
        if cached is not None:
            menu.set_files(cached)
        if self._file_index.fresh:
            return
        walking = any(
            worker.group == "file-index"
            and worker.state in {WorkerState.PENDING, WorkerState.RUNNING}
            for worker in self.workers
        )
        if not walking:
            self.run_worker(
                self._walk_workspace, thread=True, group="file-index", exit_on_error=False
            )

    def _walk_workspace(self) -> None:
        """Worker thread: rebuild the ``@`` index, then refresh the menu."""
        self._file_index.rebuild()
        if not get_current_worker().is_cancelled:
            self.call_from_thread(self._file_index_ready)

    def _file_index_ready(self) -> None:
        if self._pending_question_id is not None:
            return
        prompt = self.query_one("#prompt", PromptInput)
        mention = active_file_mention(prompt.text)
        if mention is not None:
            _start, query = mention
            self._show_file_matches(self._composer_menu(), query)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        if self._pending_question_id is not None:
            return
        text = event.text_area.text
        if text and not text.startswith("/") and "@" not in text:
            return
        menu = self._composer_menu()
        mention = active_file_mention(event.text_area.text)
        if mention is not None:
            _start, query = mention
            self._show_file_matches(menu, query)
        elif event.text_area.text.startswith("/model "):
            current = self._agent.harness.model_id if self._agent is not None else ""
            menu.set_models(
                model_matches(
                    event.text_area.text.removeprefix("/model "),
                    self._model_options,
                ),
                current,
            )
        elif event.text_area.text.startswith("/personality "):
            current = getattr(getattr(self, "config", None), "personality", None) or ""
            menu.set_personalities(
                personality_matches(event.text_area.text.removeprefix("/personality ")),
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
        command, _, argument = value[1:].partition(" ")
        if command.lower() == "addon":
            if self._busy:
                self.add_notice("/addon is unavailable while a turn is running.", "warning")
                return
            if self._agent is None:
                self.add_notice(OFFLINE_HINT, "error")
                return
            skill_tool = self._agent.harness.tools.get("skill")
            skill_instructions = (
                await skill_tool.execute(sink=None, args={"skill_id": "bundled/addon-authoring"})
                if skill_tool is not None
                else "Bundled addon-authoring skill is unavailable; inspect core_harness.extensions and "
                "the installed addon documentation before proceeding."
            )
            prompt = (
                "Follow these Symphony addon-authoring instructions, then create or improve a "
                "user addon for this request. Use the supported addon API and user addon "
                "directory documented here. Do not modify Symphony's built-in source unless "
                "I explicitly ask.\n\n"
                f"{skill_instructions}"
            )
            if argument.strip():
                prompt += f"\n\nAddon request: {argument.strip()}"
            self._start_turn(QueuedTurn(prompt, prompt, (), ()))
            return
        await self._command_manager.run(value)

    def add_update(self, text: str, hint: str = "") -> None:
        """Show a banner above the composer. Only the app has one; composer-less
        views such as the child transcript leave this undefined, so the event
        presenter falls back to a transcript notice."""
        overlay = self.query_one("#composer-overlay", ComposerOverlay)
        overlay.show(text, hint or DEFAULT_HINT)

    def _update_composer_hint(self) -> None:
        """Refresh the mode badge and the footer keyboard hint for the current state."""
        self.query_one("#composer", Composer).set_class(
            self.mode == "plan", "plan-mode"
        )
        self.query_one("#composer-mode", Static).update(mode_label(self.mode))
        self._set_status("")
