"""Conversation widgets used by the coding-agent terminal UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from rich.console import Group
from rich.text import Text
from textual.containers import Container
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
            Text("Enter sends  ·  Ctrl+D quits  ·  Ctrl+L clears", style="#575757"),
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


class RunProcess(Collapsible):
    """One turn's reasoning, tools, and usage behind a clickable header."""

    def __init__(self, thinking: ThinkingStatus) -> None:
        self._pending_items: list[Static] = []
        super().__init__(
            thinking,
            title="Working…",
            collapsed=False,
            collapsed_symbol="▸",
            expanded_symbol="▾",
            classes="run-process",
        )

    def add_item(self, widget: Static) -> None:
        if not self.is_mounted:
            self._contents_list.append(widget)
            return
        contents = self.query(Collapsible.Contents)
        if contents:
            contents.first().mount(widget)
        else:
            self._pending_items.append(widget)

    def on_mount(self) -> None:
        self.call_after_refresh(self._flush_pending_items)

    def _flush_pending_items(self) -> None:
        if not self._pending_items:
            return
        contents = self.query_one(Collapsible.Contents)
        pending, self._pending_items = self._pending_items, []
        contents.mount(*pending)

    def complete(self, title: str, *, collapse: bool = True) -> None:
        self.title = title
        self.collapsed = collapse


class ReasoningWidget(Static):
    """A live, muted reasoning summary streamed by supported models."""

    def __init__(self, content: str = "") -> None:
        super().__init__(classes="reasoning-summary")
        self.set_content(content)

    def set_content(self, content: str) -> None:
        self.reasoning_text = content
        self.update(
            Group(
                Text("✻  REASONING SUMMARY", style="bold #777777"),
                themed_markdown(content or " ", style="#777777"),
            )
        )


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
        if self._commands:
            return f"/{self._commands[self.selected_index].name}"
        return ""

    def move_selection(self, offset: int) -> None:
        count = (
            len(self._models)
            or len(self._modes)
            or len(self._plans)
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
            self.display = False
            return
        self._commands = commands
        self._models = ()
        self._modes = ()
        self._plans = ()
        self.selected_index = 0
        self._render_options()

    def set_models(self, models: tuple[ModelOption, ...], current: str = "") -> None:
        if not models:
            self._commands = ()
            self._models = ()
            self._modes = ()
            self._plans = ()
            self.display = False
            return
        self._commands = ()
        self._models = models
        self._modes = ()
        self._plans = ()
        self._current_model = current
        self.selected_index = 0
        self._render_options()

    def set_modes(self, modes: tuple[ModeOption, ...], current: str = "") -> None:
        if not modes:
            self._commands = ()
            self._models = ()
            self._modes = ()
            self._plans = ()
            self.display = False
            return
        self._commands = ()
        self._models = ()
        self._modes = modes
        self._plans = ()
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
        self._current_plan = current
        self.selected_index = 0
        self._render_options()

    def _render_options(self) -> None:
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
