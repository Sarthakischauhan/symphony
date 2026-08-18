"""Conversation widgets used by the coding-agent terminal UI."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from rich.console import Group
from rich.text import Text
from textual.containers import Container, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Static

from coding_agent.tui.commands import ModeOption, ModelOption, PlanOption, SlashCommand
from coding_agent.tui.theme import themed_markdown
from coding_agent.utils.diff import diff_stats, make_unified_diff
from coding_agent.utils.text import clip_text, compact_json


class TopBar(Static):
    """Small, product-like header instead of Textual's application chrome."""

    def set_context(self, workspace: Path, model: str = "") -> None:
        title = Text("◆  symphony", style="bold #e6e6e6")
        location = str(workspace.parent / workspace.name)
        title.append(f"   {location}", style="#777777")
        if model:
            title.append(f"   {model}", style="#626262")
        self.update(title)


class Welcome(Static):
    def __init__(self, workspace: Path) -> None:
        body = Group(
            Text("Symphony", style="bold #f0f0f0"),
            Text("Coding agent", style="#858585"),
            Text(""),
            Text(f"  {workspace}", style="#666666"),
            Text(""),
            Text("Describe a task, ask a question, or request a code change.", style="#a0a0a0"),
            Text("Enter sends  ·  Esc cancels a run  ·  Ctrl+D quits  ·  Ctrl+L clears", style="#575757"),
        )
        super().__init__(body, classes="welcome")


class UserMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__(
            Group(Text("YOU", style="bold #8a8a8a"), Text(content)),
            classes="message user-message",
        )


class AssistantMessage(Static):
    def __init__(self, content: str = "") -> None:
        super().__init__(classes="message assistant-message")
        self.set_content(content)

    def set_content(self, content: str) -> None:
        self.message_text = content
        self.update(
            Group(
                Text("◆  SYMPHONY", style="bold #d0d0d0"),
                themed_markdown(content or " "),
            )
        )


class ThinkingStatus(Static):
    """Muted run/usage metadata displayed directly beneath the user prompt."""

    def __init__(self, text: str = "Thinking…") -> None:
        super().__init__(classes="thinking-status")
        self.set_text(text)

    def set_text(self, value: str) -> None:
        self.update(Text(f"✻  {value}", style="#666666"))


class RunProcess(Container):
    """One run's flat timeline of live status, thoughts, and tools."""

    def __init__(self, thinking: ThinkingStatus) -> None:
        self._pending_items: list[Widget] = []
        self._thinking = thinking
        self._completed = False
        super().__init__(classes="run-process")

    def compose(self):  # type: ignore[no-untyped-def]
        pending, self._pending_items = self._pending_items, []
        yield self._thinking
        yield from pending

    def add_item(self, widget: Widget) -> None:
        if not self.is_attached:
            self._pending_items.append(widget)
            return
        self.mount(widget)

    def on_mount(self) -> None:
        self.call_after_refresh(self._flush_pending_items)

    def _flush_pending_items(self) -> None:
        if not self._pending_items:
            return
        pending, self._pending_items = self._pending_items, []
        self.mount(*pending)

    def complete(self, title: str, *, collapse: bool = True) -> None:
        del collapse
        if self._completed:
            return
        self._completed = True
        self._thinking.display = False
        self.add_item(
            Static(Text(f"✓  {title}", style="#5f6a62"), classes="process-complete")
        )


class ReasoningWidget(Collapsible):
    """A live tail-following thought that folds into the tool timeline."""

    def __init__(self, content: str = "") -> None:
        self._summary_heading: str | None = None
        self._content_without_heading = content
        self._body = Static(classes="reasoning-text")
        self._scroll = VerticalScroll(self._body, classes="reasoning-scroll")
        super().__init__(
            self._scroll,
            title="Thinking…",
            collapsed=False,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            classes="reasoning-block is-live",
        )
        self.set_content(content)

    def set_content(self, content: str) -> None:
        self.reasoning_text = content
        self._summary_heading, self._content_without_heading = (
            self._extract_summary_heading(content)
        )
        self._body.update(themed_markdown(content or " ", style="#858585"))
        if self.is_mounted:
            self._scroll.scroll_end(animate=False, force=True)

    @staticmethod
    def _extract_summary_heading(content: str) -> tuple[str | None, str]:
        """Return a standalone leading Markdown heading and the remaining body."""
        match = re.match(
            r"\A[ \t]*(?:"
            r"#{1,6}[ \t]+(?P<atx>[^\n]+?)[ \t]*#*"
            r"|\*\*(?P<bold>[^\n]+?)\*\*"
            r"|__(?P<underscore>[^\n]+?)__"
            r")[ \t]*(?:\n[ \t]*\n|\Z)",
            content,
        )
        if match is None:
            return None, content
        heading = next(value for value in match.groupdict().values() if value)
        return heading.strip(), content[match.end() :]

    def on_mount(self) -> None:
        self._scroll.anchor()

    def complete(self) -> None:
        self._scroll.anchor(False)
        self._scroll.scroll_home(animate=False, force=True)
        if self._summary_heading:
            self.title = f"Thought - {self._summary_heading}"
            self._body.update(
                themed_markdown(self._content_without_heading or " ", style="#858585")
            )
        else:
            self.title = "Thought"
        self.collapsed = True
        self.remove_class("is-live")
        self.add_class("is-complete")


class Notice(Static):
    COLORS = {
        "info": "#707070",
        "warning": "#d7a84b",
        "error": "#e06c75",
        "success": "#70a879",
    }

    def __init__(self, text: str, tone: str = "info") -> None:
        color = self.COLORS.get(tone, self.COLORS["info"])
        super().__init__(Text(f"  {text}", style=color), classes=f"notice {tone}")


class ToolCallWidget(Collapsible):
    """A collapsible tool lifecycle card that updates as arguments/results arrive."""

    LABELS = {
        "bash": ("Bash", "$"),
        "search": ("Search", "⌕"),
        "write_file": ("Write", "+"),
        "patch": ("Edit", "±"),
    }

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._body = Static()
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments: dict[str, Any] = {}
        self.raw_arguments = ""
        self.result = ""
        self.status = "preparing"
        super().__init__(
            self._body,
            title="",
            collapsed=False,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            classes="tool-call",
        )
        self.refresh_content()

    def set_arguments(self, arguments: Mapping[str, Any] | None, raw: str = "") -> None:
        self.arguments = dict(arguments or {})
        self.raw_arguments = raw
        self.refresh_content()

    def set_running(self, arguments: Mapping[str, Any] | None) -> None:
        self.status = "running"
        self.arguments = dict(arguments or {})
        self.collapsed = False
        self.refresh_content()

    def set_result(self, result: Any) -> None:
        self.status = "failed" if str(result).startswith(("error:", "exit=")) else "done"
        self.result = str(result or "")
        self.collapsed = self.status == "done"
        self.refresh_content()

    def _tool_title(self) -> tuple[str, str]:
        return self.LABELS.get(self.tool_name, (self.tool_name.replace("_", " ").title(), "›"))

    def _summary(self) -> str:
        if self.tool_name == "bash":
            return str(self.arguments.get("command") or self.raw_arguments)
        if self.tool_name == "search":
            return str(
                self.arguments.get("query")
                or self.arguments.get("pattern")
                or compact_json(self.arguments)
            )
        if self.tool_name in {"write_file", "patch"}:
            return str(self.arguments.get("path") or compact_json(self.arguments))
        return compact_json(self.arguments) or self.raw_arguments

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        lines = self.result.splitlines()
        if self.tool_name == "bash":
            return clip_text("\n".join(lines[-4:]), 360)
        return clip_text(self.result, 260)

    def _body_rows(self) -> list[Any]:
        rows: list[Any] = []
        summary = clip_text(self._summary(), 300)
        if summary:
            rows.append(Text(f"   {summary}", style="#a4a4a4"))
        result = self._result_summary()
        if result:
            _label, icon = self._tool_title()
            result_color = "#d66b73" if self.status == "failed" else "#666666"
            rows.append(Text(f"   {icon}  {result}", style=result_color))
        return rows

    def refresh_content(self) -> None:
        label, _icon = self._tool_title()
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        summary = clip_text(self._summary(), 140)
        title = f"{marker}  {label}"
        if summary:
            title = f"{title} ({summary})"
        self.title = title
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        self._body.update(Group(*self._body_rows()))


class ReadFileWidget(ToolCallWidget):
    """Compact, path-oriented presentation for the read_file tool."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Read", "└")

    def _summary(self) -> str:
        path = self.arguments.get("path")
        if not path:
            return self.raw_arguments
        offset = int(self.arguments.get("offset") or 1)
        limit = int(self.arguments.get("limit") or 0)
        window = ""
        if offset != 1 or limit:
            end = offset + limit - 1 if limit else "…"
            window = f"  lines {offset}–{end}"
        return f"{path}{window}"

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        if self.result.startswith("error:"):
            return self.result
        count = len(self.result.splitlines())
        size = len(self.result.encode("utf-8"))
        return f"Read {count} lines ({size:,} bytes)"


class PatchDiffWidget(ToolCallWidget):
    """Unified diff presentation for the exact-text patch tool."""

    MAX_DIFF_LINES = 80

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__(call_id, tool_name)
        self.add_class("diff-tool")

    def _diff(self) -> list[str]:
        old = str(self.arguments.get("old_str") or "")
        new = str(self.arguments.get("new_str") or "")
        if not old and not new:
            return []
        path = str(self.arguments.get("path") or "file")
        return make_unified_diff(old, new, path)

    def _stats(self, diff: list[str]) -> tuple[int, int]:
        return diff_stats(diff)

    def refresh_content(self) -> None:
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        path = str(self.arguments.get("path") or "")
        diff = self._diff()
        additions, deletions = self._stats(diff)

        title = f"{marker}  Update"
        if path:
            title = f"{title} ({path})"
        if diff:
            title = f"{title}  +{additions} -{deletions}"
        self.title = title
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        rows: list[Any] = []

        visible = diff[: self.MAX_DIFF_LINES]
        for line in visible:
            if line.startswith("@@"):
                rows.append(Text(f"   {line}", style="#6688a8"))
            elif line.startswith("+"):
                rows.append(Text(f"   {line}", style="#8fc49a on #203026"))
            elif line.startswith("-"):
                rows.append(Text(f"   {line}", style="#df8b91 on #352225"))
            else:
                rows.append(Text(f"   {line}", style="#686868"))
        if len(diff) > self.MAX_DIFF_LINES:
            hidden = len(diff) - self.MAX_DIFF_LINES
            rows.append(Text(f"   … {hidden} diff lines hidden", style="#555555"))

        if self.result:
            result_color = "#d66b73" if self.status == "failed" else "#626262"
            rows.append(Text(f"   └  {clip_text(self.result, 260)}", style=result_color))
        self._body.update(Group(*rows))


def make_tool_widget(call_id: str, tool_name: str) -> ToolCallWidget:
    if tool_name == "read_file":
        return ReadFileWidget(call_id, tool_name)
    if tool_name == "patch":
        return PatchDiffWidget(call_id, tool_name)
    return ToolCallWidget(call_id, tool_name)


class Composer(Container):
    """Input surface with an always-visible interaction hint."""

    def compose(self):  # type: ignore[no-untyped-def]
        yield Input(placeholder="Ask Symphony to build, fix, or explain…", id="prompt")
        yield Static("BUILD · Tab mode · Enter to send", id="composer-hint")


class SlashMenu(Static):
    """Discoverable command suggestions displayed above the composer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.selected_index = 0
        self._commands: tuple[SlashCommand, ...] = ()
        self._models: tuple[ModelOption, ...] = ()
        self._modes: tuple[ModeOption, ...] = ()
        self._plans: tuple[PlanOption, ...] = ()
        self._questions: tuple[str, ...] = ()
        self._question_text = ""
        self._current_model = ""
        self._current_mode = ""
        self._current_plan = ""

    @property
    def selected_value(self) -> str:
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

    def move_selection(self, offset: int) -> None:
        count = (
            len(self._models)
            or len(self._modes)
            or len(self._plans)
            or len(self._questions)
            or len(self._commands)
        )
        if not count:
            return
        self.selected_index = (self.selected_index + offset) % count
        self._render_options()

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        if not commands:
            self._commands = ()
            self._models = ()
            self._modes = ()
            self._plans = ()
            self._questions = ()
            self._question_text = ""
            self.display = False
            return
        self._commands = commands
        self._models = ()
        self._modes = ()
        self._plans = ()
        self._questions = ()
        self._question_text = ""
        self.selected_index = 0
        self._render_options()

    def set_models(self, models: tuple[ModelOption, ...], current: str = "") -> None:
        if not models:
            self._commands = ()
            self._models = ()
            self._modes = ()
            self._plans = ()
            self._questions = ()
            self._question_text = ""
            self.display = False
            return
        self._commands = ()
        self._models = models
        self._modes = ()
        self._plans = ()
        self._questions = ()
        self._question_text = ""
        self._current_model = current
        self.selected_index = 0
        self._render_options()

    def set_modes(self, modes: tuple[ModeOption, ...], current: str = "") -> None:
        if not modes:
            self._commands = ()
            self._models = ()
            self._modes = ()
            self._plans = ()
            self._questions = ()
            self._question_text = ""
            self.display = False
            return
        self._commands = ()
        self._models = ()
        self._modes = modes
        self._plans = ()
        self._questions = ()
        self._question_text = ""
        self._current_mode = current
        self.selected_index = 0
        self._render_options()

    def set_plans(self, plans: tuple[PlanOption, ...], current: str = "") -> None:
        if not plans:
            self.set_commands(())
            return
        self._commands = ()
        self._models = ()
        self._modes = ()
        self._plans = plans
        self._questions = ()
        self._question_text = ""
        self._current_plan = current
        self.selected_index = 0
        self._render_options()

    def set_question(
        self, question: str, choices: list[str], *, default: str = ""
    ) -> None:
        self._commands = ()
        self._models = ()
        self._modes = ()
        self._plans = ()
        self._questions = tuple(choices)
        self._question_text = question
        self.selected_index = choices.index(default) if default in choices else 0
        self._render_options()

    def _render_options(self) -> None:
        if self._question_text:
            rows = [Text(f"?  {self._question_text}", style="bold #d7d7d7")]
            for index, choice in enumerate(self._questions):
                pointer = "›" if index == self.selected_index else " "
                style = "bold #f2f2f2 on #383838" if index == self.selected_index else "#c5c5c5"
                rows.append(Text(f" {pointer} {choice}", style=style))
            instruction = "   ↑/↓ select  ·  Enter choose" if self._questions else "   Type an answer  ·  Enter submit"
            rows.append(Text(instruction, style="#505050"))
            self.update(Group(*rows))
            self.display = True
            return
        rows: list[Text] = []
        if self._models:
            for index, model in enumerate(self._models):
                active = "●" if model.id == self._current_model else "○"
                pointer = "›" if index == self.selected_index else " "
                style = (
                    "bold #f2f2f2 on #383838"
                    if index == self.selected_index
                    else "bold #c5c5c5"
                )
                row = Text(f" {pointer} {active} {model.id:<27}", style=style)
                row.append(model.description, style="#858585")
                rows.append(row)
        elif self._modes:
            for index, mode in enumerate(self._modes):
                active = "●" if mode.id == self._current_mode else "○"
                pointer = "›" if index == self.selected_index else " "
                style = (
                    "bold #f2f2f2 on #383838"
                    if index == self.selected_index
                    else "bold #c5c5c5"
                )
                row = Text(f" {pointer} {active} {mode.label:<27}", style=style)
                row.append(mode.description, style="#858585")
                rows.append(row)
        elif self._plans:
            for index, plan in enumerate(self._plans):
                active = "●" if plan.id == self._current_plan else "○"
                pointer = "›" if index == self.selected_index else " "
                style = (
                    "bold #f2f2f2 on #383838"
                    if index == self.selected_index
                    else "bold #c5c5c5"
                )
                row = Text(f" {pointer} {active} {plan.label:<27}", style=style)
                row.append(plan.description, style="#858585")
                rows.append(row)
        else:
            for index, command in enumerate(self._commands):
                pointer = "›" if index == self.selected_index else " "
                style = (
                    "bold #f2f2f2 on #383838"
                    if index == self.selected_index
                    else "bold #c5c5c5"
                )
                row = Text(f" {pointer} {command.usage:<22}", style=style)
                row.append(command.description, style="#858585")
                rows.append(row)
        rows.append(Text("   ↑/↓ select  ·  Enter choose  ·  Tab complete", style="#505050"))
        self.update(Group(*rows))
        self.display = True
