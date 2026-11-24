"""Slash-command, file, and question selection menu."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from rich.text import Text
from textual import events
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from coding_agent.commands.catalog import (
    EffortOption,
    ModelOption,
    PersonalityOption,
    SlashCommand,
)
from coding_agent.tui.screens.file_selector import FileOption
from coding_agent.tui.theme import SYMPHONY_COLORS

# Approval card copy. The choices, their order and the default are the
# harness's (``addons/approvals.py``); this only words and marks them.
APPROVAL_TOOLS: dict[str, tuple[str, str, str]] = {
    # tool name: (border label, title, prefix for the subject line)
    "bash": ("Bash", "Run this command?", "$ "),
    "web_search": ("Web Search", "Search the web?", ""),
    "write_file": ("Write", "", ""),
    "generate_image": ("Image", "", ""),
    "patch": ("Update", "", ""),
}
APPROVAL_CHOICES: dict[str, tuple[str, str]] = {
    # choice: (colour, what it means)
    "Allow once": ("#8fc49a", "just this call"),
    "Always allow": ("#e0b66b", "stop asking for anything this session"),
    "Deny": ("#df8b91", "skip it; the agent is told no"),
}
_SUBJECT = re.compile(r"`([^`]*)`")


class SlashMenu(OptionList):
    """Cached completion menu for files and commands."""

    _files_cache: tuple[FileOption, ...] | None = None
    _matches_cache: dict[tuple[str, str], tuple[Option, ...]] = {}

    @classmethod
    def clear_session_cache(cls) -> None:
        cls._files_cache = None
        cls._matches_cache.clear()

    """Discoverable command suggestions displayed above the composer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, markup=False, **kwargs)
        self.selected_index = 0
        self._option_offset = 0
        self._commands: tuple[SlashCommand, ...] = ()
        self._models: tuple[ModelOption, ...] = ()
        self._personalities: tuple[PersonalityOption, ...] = ()
        self._efforts: tuple[EffortOption, ...] = ()
        self._files: tuple[FileOption, ...] = ()
        self._questions: tuple[str, ...] = ()
        self._question_text = ""
        self._question_kind = ""
        self._question_tool = ""
        self._question_descriptions: dict[str, str] = {}
        self._multi_select = False
        self._selected_questions: set[str] = set()
        self._current_model = ""
        self._current_personality = ""
        self._current_effort = ""

    @property
    def selected_value(self) -> str:
        if self._files:
            return f"@{self._files[self.selected_index].path}"
        if self._models:
            return f"/model {self._models[self.selected_index].id}"
        if self._personalities:
            return f"/personality {self._personalities[self.selected_index].id}"
        if self._efforts:
            return f"/effort {self._efforts[self.selected_index].id}"
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
            or len(self._personalities)
            or len(self._efforts)
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
        personalities: tuple[PersonalityOption, ...] = (),
        efforts: tuple[EffortOption, ...] = (),
        files: tuple[FileOption, ...] = (),
        questions: tuple[str, ...] = (),
        question_text: str = "",
        question_kind: str = "",
        selected_index: int = 0,
    ) -> None:
        self._commands = commands
        self._models = models
        self._personalities = personalities
        self._efforts = efforts
        self._files = files
        self._questions = questions
        self._question_text = question_text
        self._question_kind = question_kind
        self.selected_index = selected_index
        self.set_class(question_kind == "approval", "permission-menu")
        self.border_title = self.approval_label() if question_kind == "approval" else None
        self.set_class(bool(files), "file-menu")

        if self._choice_count or question_text:
            self._render_options()
        elif self.display:
            self._hide()

    def _hide(self) -> None:
        self._option_offset = 0
        self.clear_options()
        self.remove_class("permission-menu")
        self.remove_class("file-menu")
        self.border_title = None
        self._question_tool = ""
        self.display = False

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self._replace_choices(commands=commands)

    def set_models(self, models: tuple[ModelOption, ...], current: str = "") -> None:
        self._current_model = current
        self._replace_choices(models=models)

    def set_personalities(
        self, personalities: tuple[PersonalityOption, ...], current: str = ""
    ) -> None:
        self._current_personality = current
        self._replace_choices(personalities=personalities)

    def set_efforts(self, efforts: tuple[EffortOption, ...], current: str = "") -> None:
        self._current_effort = current
        selected_index = next(
            (index for index, effort in enumerate(efforts) if effort.id == current),
            0,
        )
        self._replace_choices(efforts=efforts, selected_index=selected_index)


    def set_files(self, files: tuple[FileOption, ...]) -> None:
        if self._files_cache == files:
            files = self._files_cache
        else:
            self._files_cache = files
        self._replace_choices(files=files)

    def set_question(
        self,
        question: str,
        choices: list[str],
        *,
        default: str = "",
        kind: str = "",
        descriptions: dict[str, str] | None = None,
        multi_select: bool = False,
        tool_name: str = "",
    ) -> None:
        self._question_tool = tool_name
        self._question_descriptions = descriptions or {}
        self._multi_select = multi_select
        self._selected_questions = set()
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
            return rows, self._approval_headers(), " ↑↓ choose  ·  Enter confirm  ·  Esc deny"

        rows = []
        for index, choice in enumerate(self._questions, 1):
            mark = ("[x] " if choice in self._selected_questions else "[ ] ") if self._multi_select else ""
            row = Text(f"   {index}. {mark}{choice}", style="#c5c5c5")
            if self._question_descriptions.get(choice):
                row.append(f"  — {self._question_descriptions[choice]}", style="#858585")
            rows.append(row)
        headers = [Text(f"?  {self._question_text}", style="bold #d7d7d7")]
        hint = (
            "   ↑/↓ move  ·  Space toggle  ·  Enter submit  ·  type a custom answer"
            if self._multi_select else
            "   ↑/↓ select  ·  Enter choose  ·  type a custom answer"
            if self._questions else "   Type an answer  ·  Enter submit"
        )
        return rows, headers, hint

    @staticmethod
    def _approval_choice(choice: str) -> Text:
        """One choice: the label, then what choosing it does."""
        colour, meaning = APPROVAL_CHOICES.get(choice, ("#c5c5c5", ""))
        row = Text(" ")
        row.append(f"{choice:<14}", style=f"bold {colour}")
        if meaning:
            row.append(meaning, style="#6e6e6e")
        return row

    def _choice_rows(self) -> list[Text]:
        if self._files:
            return [self._file_row(file) for file in self._files]
        if self._models:
            return [self._model_row(model) for model in self._models]
        if self._personalities:
            return [
                self._described_row(
                    f"{'●' if item.id == self._current_personality else '○'} {item.id:<27}",
                    item.description,
                )
                for item in self._personalities
            ]
        if self._efforts:
            return [
                self._described_row(
                    f"{'●' if effort.id == self._current_effort else '○'} {effort.label:<27}",
                    effort.description,
                )
                for effort in self._efforts
            ]
        return [
            self._described_row(f"{command.usage:<22}", command.description)
            for command in self._commands
        ]

    def _model_row(self, model: ModelOption) -> Text:
        """Active model gets a mark. The rest stay plain so the list can scroll."""
        current = model.id == self._current_model
        name = model.label or model.id.split(":", 1)[-1]
        provider = model.id.split(":", 1)[0]
        row = Text("  ▸ " if current else "    ", style=f"bold {SYMPHONY_COLORS['accent']}")
        row.append(name, style="bold #ededed" if current else "#d0d0d0")
        row.append(f"   {provider}", style="#737373")
        if model.description and model.description != provider:
            detail = model.description.split("·", 1)[-1].strip()
            row.append(f"  {detail}", style="#5f5f5f")
        return row

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
        """A title that says what is being asked, then the exact subject.

        The harness asks "Allow bash command once?" with the command on the
        next line, or "Overwrite existing file `path`?" in one line. The title
        drops the quoted subject; the subject gets a line of its own.
        """
        summary, _, detail = self._question_text.partition("\n")
        # The TUI appends the size of a write: "… `a.py`? (1,234 bytes)".
        size = re.search(r"\s*\(([\d,]+ bytes)\)\s*$", summary)
        if size:
            summary = summary[: size.start()]
        _label, title, prefix = APPROVAL_TOOLS.get(self._question_tool, ("", "", ""))
        quoted = _SUBJECT.search(summary)
        subject = detail.strip().strip("`") or (quoted.group(1) if quoted else "")
        if not title:
            title = " ".join(_SUBJECT.sub("", summary).split()).replace(" to ?", "?").replace(" ?", "?")
            title = title or "Allow this?"
        heading = Text(f" {title}", style="bold #e8e8e8")
        if size:
            heading.append(f"  {size.group(1)}", style="#6e6e6e")
        headers = [heading]
        if subject:
            block = Text()
            for index, line in enumerate(subject.splitlines() or [subject]):
                if index:
                    block.append("\n")
                block.append(" ┃ ", style="#a77f3d")
                block.append(prefix if index == 0 else " " * len(prefix), style="#8a8a8a")
                block.append(line, style="#d8d8d8")
            headers.append(block)
        headers.append(Text(""))  # breathing room before the choices
        return headers

    def approval_label(self) -> str:
        """The tool named on the card's border, or "Permission" when unknown."""
        return APPROVAL_TOOLS.get(self._question_tool, ("Permission", "", ""))[0] or "Permission"
