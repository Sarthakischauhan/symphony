"""Context window overview."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTEXT_MODAL_CSS
from core_harness.context import ContextReport

_ROLE_COLORS = {
    "system": "#738794",
    "user": "#8eafc2",
    "assistant": "#c7b66e",
    "tool": "#79a985",
    "skills": "#b38bc4",
    "schemas": "#d99a63",
}


class ContextModal(ModalBase[None]):
    """Estimated conversation usage and current extension inventory."""

    CSS = CONTEXT_MODAL_CSS

    def __init__(
        self,
        report: ContextReport,
        *,
        skills: tuple[str, ...] = (),
        skill_tokens: int = 0,
        plugins: tuple[str, ...] = (),
        tool_tokens: int = 0,
        tool_count: int = 0,
    ) -> None:
        super().__init__()
        self.report = report
        self.skills = skills
        self.skill_tokens = skill_tokens
        self.plugins = plugins
        self.tool_tokens = tool_tokens
        self.tool_count = tool_count

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="context-pane", classes="modal-pane"):
            with Horizontal(id="context-header"):
                yield Static("Context", id="context-title")
                yield ModalCloseButton("Esc", id="modal-close")
            with ModalScroll(id="context-body", classes="modal-body"):
                yield Static(self._render_meters(), id="context-meters")

    def _render_meters(self) -> Text:
        system_tokens = next((bucket.tokens for bucket in self.report.buckets if bucket.role == "system"), 0)
        skill_tokens = min(self.skill_tokens, system_tokens)
        categories = [(bucket.role, bucket.label, bucket.tokens - skill_tokens if bucket.role == "system" else bucket.tokens)
                      for bucket in self.report.buckets]
        categories.extend((("skills", "Skills", skill_tokens), ("schemas", "Tool schemas", self.tool_tokens)))
        used = self.report.stored_tokens + self.tool_tokens
        limit = self.report.context_limit
        text = Text()
        text.append(f"~{used:,}", style="bold #e4e8e7")
        if limit:
            text.append(f" / {limit:,} tokens", style="#818f94")
            text.append(f"   ·   {used / limit * 100:.1f}%\n\n", style="bold #c7b66e")
            boundaries: list[tuple[int, str]] = []
            total = 0
            for role, _label, tokens in categories:
                if tokens:
                    total += tokens
                    boundaries.append((min(100, round(total * 100 / limit)), role))
            for cell in range(100):
                role = next((role for boundary, role in boundaries if cell < boundary), None)
                text.append("■ " if role else "□ ", style=_ROLE_COLORS.get(role or "", "#444444"))
                if cell % 10 == 9:
                    text.append("\n")
            text.append("\n")
        else:
            text.append(" tokens   ·   limit unknown\n\n", style="#818f94")
        for role, label, tokens in categories:
            if tokens:
                share = f"  ·  {tokens / limit * 100:.1f}%" if limit else ""
                text.append("■ ", style=_ROLE_COLORS.get(role, "#bdbdbd"))
                text.append(f"{label:<14} ~{tokens:,}{share}\n", style="#bdbdbd")
        if limit:
            remaining = max(limit - used, 0)
            text.append(f"□ Remaining       ~{remaining:,}  ·  {remaining / limit * 100:.1f}%\n", style="#777777")
        text.append(f"\nSkills  ·  {len(self.skills)} listed\n", style="bold #b38bc4")
        for skill in self.skills:
            text.append(f"  ■ {skill}\n", style="#b38bc4")
        if not self.skills:
            text.append("  None listed\n", style="#818f94")
        text.append(f"\nPlugins  ·  {len(self.plugins)} enabled\n", style="bold #79a985")
        for plugin in self.plugins:
            text.append(f"  □ {plugin}  ·  token cost unavailable\n", style="#79a985")
        if not self.plugins:
            text.append("  None enabled\n", style="#818f94")
        text.append(f"\n{self.tool_count} tool schemas  ·  estimated usage", style="#68777b")
        return text
