"""Slash-command, file, and question selection menu."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from rich.text import Text
from textual import events
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from coding_agent.tui.commands import ModeOption, ModelOption, PlanOption, SlashCommand
from coding_agent.tui.file_selector import FileOption


class SlashMenu(OptionList):
    """Discoverable command suggestions displayed above the composer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, markup=False, **kwargs)
        self.selected_index = 0
        self._option_offset = 0
        self._commands: tuple[SlashCommand, ...] = ()
        self._models: tuple[ModelOption, ...] = ()
        self._modes: tuple[ModeOption, ...] = ()
        self._plans: tuple[PlanOption, ...] = ()
        self._files: tuple[FileOption, ...] = ()
        self._questions: tuple[str, ...] = ()
        self._question_text = ""
        self._question_kind = ""
        self._current_model = ""
        self._current_mode = ""
        self._current_plan = ""

    @property
    def selected_value(self) -> str:
        if self._files:
            return f"@{self._files[self.selected_index].path}"
        if self._models:
            return f"/model {self._models[self.selected_index].id}"
        if self._modes:
            return f"/mode {self._modes[self.selected_index].id}"
        if self._plans:
            return f"/plan {self._plans[self.selected_index].id}"
        if self._questions:
            return self._questions[self.selected_index]
        if self._commands:
            return f"/{self._commands[self.selected_index].name}"
        return ""

    @property
    def is_file_selector(self) -> bool:
        return bool(self._files)

    @property
    def _choice_count(self) -> int:
        return (
            len(self._files)
            or len(self._models)
            or len(self._modes)
            or len(self._plans)
            or len(self._questions)
            or len(self._commands)
        )

    def move_selection(self, offset: int) -> None:
        count = self._choice_count
        if not count:
            return
        self.selected_index = (self.selected_index + offset) % count
        self.highlighted = self.selected_index + self._option_offset

    def _move_pointer_selection(self, offset: int) -> None:
        """Move selection without wrapping at the ends for pointer scrolling."""
        selected_index = min(
            max(0, self.selected_index + offset), self._choice_count - 1
        )
        if selected_index != self.selected_index:
            self.selected_index = selected_index
            self.highlighted = selected_index + self._option_offset

    def select_option_index(self, option_index: int) -> bool:
        """Synchronize selection from an OptionList pointer event."""
        selected_index = option_index - self._option_offset
        if not 0 <= selected_index < self._choice_count:
            return False
        self.selected_index = selected_index
        self.highlighted = option_index
        return True

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Keep pointer hover and keyboard selection on the same option."""
        selected_index = event.option_index - self._option_offset
        if 0 <= selected_index < self._choice_count:
            self.selected_index = selected_index

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self._choice_count:
            self._move_pointer_selection(1)
            event.prevent_default()
            event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self._choice_count:
            self._move_pointer_selection(-1)
            event.prevent_default()
            event.stop()

    def _replace_choices(
        self,
        *,
        commands: tuple[SlashCommand, ...] = (),
        models: tuple[ModelOption, ...] = (),
        modes: tuple[ModeOption, ...] = (),
        plans: tuple[PlanOption, ...] = (),
        files: tuple[FileOption, ...] = (),
        questions: tuple[str, ...] = (),
        question_text: str = "",
        question_kind: str = "",
        selected_index: int = 0,
    ) -> None:
        self._commands = commands
        self._models = models
        self._modes = modes
        self._plans = plans
        self._files = files
        self._questions = questions
        self._question_text = question_text
        self._question_kind = question_kind
        self.selected_index = selected_index
        self.set_class(question_kind == "approval", "permission-menu")
        self.set_class(bool(files), "file-menu")

        if self._choice_count or question_text:
            self._render_options()
        else:
            self._hide()

    def _hide(self) -> None:
        self._option_offset = 0
        self.clear_options()
        self.remove_class("permission-menu")
        self.remove_class("file-menu")
        self.display = False

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self._replace_choices(commands=commands)

    def set_models(self, models: tuple[ModelOption, ...], current: str = "") -> None:
        self._current_model = current
        self._replace_choices(models=models)

    def set_modes(self, modes: tuple[ModeOption, ...], current: str = "") -> None:
        self._current_mode = current
        self._replace_choices(modes=modes)

    def set_plans(self, plans: tuple[PlanOption, ...], current: str = "") -> None:
        self._current_plan = current
        self._replace_choices(plans=plans)

    def set_files(self, files: tuple[FileOption, ...]) -> None:
        self._replace_choices(files=files)

    def set_question(
        self,
        question: str,
        choices: list[str],
        *,
        default: str = "",
        kind: str = "",
    ) -> None:
        selected_index = choices.index(default) if default in choices else 0
        self._replace_choices(
            questions=tuple(choices),
            question_text=question,
            question_kind=kind,
            selected_index=selected_index,
        )

    def _render_options(self) -> None:
        if self._question_text:
            rows, headers, hint = self._question_rows()
            self._set_rendered_options(rows, headers=headers, hint=hint)
            return

        rows = self._choice_rows()
        if self._files:
            self._set_rendered_options(
                rows,
                headers=[Text("  FILES", style="#666666")],
                hint="  ↑↓ select   Tab insert   Enter choose",
            )
            return
        self._set_rendered_options(
            rows, hint="   ↑/↓ select  ·  Enter choose  ·  Tab complete"
        )

    def _question_rows(self) -> tuple[list[Text], list[Text], str]:
        if self._question_kind == "approval":
            rows = [self._approval_choice(choice) for choice in self._questions]
            return rows, self._approval_headers(), "   Enter confirm  ·  Esc deny"

        rows = [Text(f"   {choice}", style="#c5c5c5") for choice in self._questions]
        headers = [Text(f"?  {self._question_text}", style="bold #d7d7d7")]
        hint = (
            "   ↑/↓ select  ·  Enter choose"
            if self._questions
            else "   Type an answer  ·  Enter submit"
        )
        return rows, headers, hint

    @staticmethod
    def _approval_choice(choice: str) -> Text:
        if choice == "Allow once":
            return Text("   ✓  Allow once", style="bold #8fc49a")
        if choice == "Deny":
            return Text("   ×  Deny", style="bold #df8b91")
        return Text(f"   {choice}", style="#c5c5c5")

    def _choice_rows(self) -> list[Text]:
        if self._files:
            return [self._file_row(file) for file in self._files]
        if self._models:
            return [
                self._described_row(
                    f"{'●' if model.id == self._current_model else '○'} {model.id:<27}",
                    model.description,
                )
                for model in self._models
            ]
        if self._modes:
            return [
                self._described_row(
                    f"{'●' if mode.id == self._current_mode else '○'} {mode.label:<27}",
                    mode.description,
                )
                for mode in self._modes
            ]
        if self._plans:
            return [
                self._described_row(
                    f"{'●' if plan.id == self._current_plan else '○'} {plan.label:<27}",
                    plan.description,
                )
                for plan in self._plans
            ]
        return [
            self._described_row(f"{command.usage:<22}", command.description)
            for command in self._commands
        ]

    @staticmethod
    def _described_row(label: str, description: str) -> Text:
        row = Text(f"   {label}", style="bold #c5c5c5")
        row.append(description, style="#858585")
        return row

    @staticmethod
    def _file_row(file: FileOption) -> Text:
        path = PurePosixPath(file.path)
        parent = "" if str(path.parent) == "." else f"{path.parent}/"
        row = Text("  @  ", style="#7085ba")
        row.append(parent, style="#737373")
        row.append(path.name, style="#d0d0d0")
        occupied = 5 + len(parent) + len(path.name)
        row.append(" " * max(3, 58 - occupied))
        row.append(file.description, style="#5f5f5f")
        return row

    def _set_rendered_options(
        self,
        rows: list[Text],
        *,
        headers: list[Text] | None = None,
        hint: str,
    ) -> None:
        headers = headers or []
        self._option_offset = len(headers)
        options = [Option(header, disabled=True) for header in headers]
        options.extend(
            Option(row, id=f"choice-{index}") for index, row in enumerate(rows)
        )
        options.append(Option(Text(hint, style="#505050"), disabled=True))
        self.set_options(options)
        if rows:
            self.selected_index = min(self.selected_index, len(rows) - 1)
            self.highlighted = self.selected_index + self._option_offset
        self.display = True

    def _approval_headers(self) -> list[Text]:
        summary, _, detail = self._question_text.partition("\n")
        action = detail.strip().strip("`") or summary.replace("`", "")
        preview = Text()
        for index, line in enumerate(action.splitlines() or [action]):
            if index:
                preview.append("\n")
            preview.append("  │ ", style="#666666")
            preview.append(line, style="bold #d0d0d0")
        return [
            Text("  Allow Symphony to run the following command?", style="bold #d0d0d0"),
            preview,
        ]
