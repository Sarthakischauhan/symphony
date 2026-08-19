"""Coordinator for the TUI's slash commands."""

from __future__ import annotations

from typing import Any

from coding_agent.tui.commands import SLASH_COMMANDS
from coding_agent.tui.modal import DiffModal, LearningModal
from coding_agent.tui.commands.mode_switcher import select_mode, show_mode_picker
from coding_agent.tui.commands.model_switcher import select_model, show_model_picker
from coding_agent.tui.commands.plan_list import (
    open_plan_modal,
    on_plan_action,
    plan_options as list_plan_options,
    show_plan_picker,
)
from coding_agent.tui.commands.reload import reload_project
from coding_agent.tui.commands.session import start_new_session
from coding_agent.tui.commands.status import show_status


class CommandManager:
    """Parse slash commands and delegate behavior to focused command modules."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def plan_options(self, query: str = ""):
        return list_plan_options(self.app, query)

    async def run(self, value: str) -> None:
        command, _, argument = value[1:].partition(" ")
        command = command.lower().strip()
        argument = argument.strip()
        app = self.app

        if command in {"quit", "exit"}:
            app.exit()
        elif command == "clear":
            app.action_clear_transcript()
        elif command == "help":
            lines = [f"{item.usage:<24} {item.description}" for item in SLASH_COMMANDS]
            app.add_notice("Slash commands\n" + "\n".join(lines))
        elif command == "status":
            show_status(app)
        elif command == "learning":
            app.push_screen(LearningModal(app.workspace))
        elif command == "plan":
            open_plan_modal(app, argument) if argument else show_plan_picker(app)
        elif command == "mode":
            if app._busy:
                app.add_notice("/mode is unavailable while a turn is running.", "warning")
            else:
                select_mode(app, argument) if argument else show_mode_picker(app)
        elif app._busy:
            app.add_notice(f"/{command} is unavailable while a turn is running.", "warning")
        elif command == "reload":
            await reload_project(app)
        elif app._agent is None:
            app.add_notice("Agent is offline. Configure OPENAI_API_KEY and restart.", "error")
        elif command == "new":
            start_new_session(app)
        elif command == "model":
            select_model(app, argument) if argument else show_model_picker(app)
        elif command == "compact":
            before, after = await app._agent.compact_conversation()
            if before == 0:
                app.add_notice("There is no saved conversation to compact.")
            elif before == after:
                app.add_notice(f"Context is already compact · {after} messages")
        elif command == "diff":
            app.push_screen(DiffModal(app.workspace))
        else:
            app.add_notice(f"Unknown command: /{command}. Type /help to see commands.", "warning")

    def open_plan_modal(self, plan_name: str | None = None) -> None:
        open_plan_modal(self.app, plan_name)

    def on_plan_action(self, action: str | None) -> None:
        on_plan_action(self.app, action)
