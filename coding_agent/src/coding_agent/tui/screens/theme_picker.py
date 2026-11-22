"""``/theme``: pick a color theme and watch it applied as the highlight moves.

The list opens as a sheet over the composer, so the top bar, transcript and footer
stay visible and repaint with each highlighted theme. Enter keeps the theme
(the caller saves it), Esc dismisses with None and the caller restores the old one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.tui.screens.modal import ModalBase
from coding_agent.tui.theme import SYMPHONY_CODE_THEME, SYMPHONY_COLORS
from coding_agent.tui.theme.plugin_palette import ThemePalette

SAMPLE_CODE = '''def load(path):
    """Read the settings."""
    return {"retries": 3, "name": path.stem}
'''


@dataclass(frozen=True)
class ThemeEntry:
    """One row of the picker. ``palette`` is None for Symphony's default theme."""

    name: str
    detail: str
    palette: ThemePalette | None


class ThemePickerScreen(ModalBase[str | None]):
    """Choose a theme by name; ``preview`` is called with each highlighted entry's palette."""

    def __init__(
        self,
        entries: tuple[ThemeEntry, ...],
        current: str,
        preview: Callable[[ThemePalette | None], None],
        note: str = "",
    ) -> None:
        super().__init__()
        self._entries = entries
        self._current = current
        self._preview = preview
        self._note = note
        self._shown = current

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-pane"):
            yield Static(self._title(), id="theme-title", markup=False)
            yield OptionList(*self._options(), id="theme-list", markup=False)
            yield Static(self._sample(), id="theme-sample")

    def on_mount(self) -> None:
        names = [entry.name for entry in self._entries]
        self.query_one("#theme-list", OptionList).highlighted = names.index(self._current) if self._current in names else 0

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        entry = self._entries[event.option_index]
        if entry.name != self._shown:
            self._shown = entry.name
            self._preview(entry.palette)
        self.query_one("#theme-sample", Static).update(self._sample())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self._entries[event.option_index].name)

    def _title(self) -> str:
        hint = "↑↓ preview  ·  Enter use  ·  Esc cancel"
        return f"Theme  ·  {hint}" + (f"\n{self._note}" if self._note else "")

    def _options(self) -> list[Option]:
        width = max(len(entry.name) for entry in self._entries)
        options: list[Option] = []
        for entry in self._entries:
            row = Text("● " if entry.name == self._current else "○ ")
            row.append(entry.name.ljust(width + 2), style="bold")
            row.append(entry.detail, style="dim")
            options.append(Option(row, id=entry.name))
        return options

    def _sample(self) -> RenderableType:
        colors = SYMPHONY_COLORS
        status = Text()
        for label, key in (("accent", "accent"), ("success", "string"), ("warning", "number"), ("error", "keyword"), ("muted", "muted")):
            status.append(f" {label} ", style=f"bold {colors[key]}")
        diff = Text()
        diff.append("+ added line\n", style=f"{colors['string']} on {colors.get('diff_added', colors['surface'])}")
        diff.append("- removed line", style=f"{colors['keyword']} on {colors.get('diff_removed', colors['overlay'])}")
        return Group(status, Syntax(SAMPLE_CODE, "python", theme=SYMPHONY_CODE_THEME), diff)


__all__ = ["ThemeEntry", "ThemePickerScreen"]
