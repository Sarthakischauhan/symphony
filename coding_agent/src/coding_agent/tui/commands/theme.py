"""``/theme``: open the live-preview picker, or switch straight to a named theme."""

from __future__ import annotations

from typing import TYPE_CHECKING

from coding_agent.commands.themes_cli import available_themes, choose_theme
from coding_agent.config import DEFAULT_THEME, user_theme_path
from coding_agent.tui.screens.theme_picker import ThemeEntry, ThemePickerScreen
from coding_agent.tui.theme.active import selected_palette
from coding_agent.tui.theme.plugin_palette import ThemePalette, palette_for

if TYPE_CHECKING:
    from coding_agent.tui.app import CodingAgentApp

OVERRIDE_NOTE = "Your theme.toml overrides every theme, so previews will not change the colors."


def theme_entries(app: CodingAgentApp) -> tuple[ThemeEntry, ...]:
    entries = [ThemeEntry(DEFAULT_THEME, "Symphony", None)]
    for theme in available_themes(app.workspace, app.config):
        entries.append(ThemeEntry(theme.qualified_name, theme.base, palette_for(theme)))
    return tuple(entries)


def select_theme(app: CodingAgentApp, argument: str) -> None:
    """Use the theme ``argument`` names and save it."""
    try:
        config = choose_theme(app.workspace, argument)
        palette = selected_palette(config, app.workspace)
    except ValueError as exc:
        app.add_notice(f"{exc}. Run /theme to see the themes.", "warning")
        return
    app.config = config
    app.show_theme(palette)
    app.add_update(f"Theme set to {config.theme}")
    if user_theme_path().is_file():
        app.add_notice(OVERRIDE_NOTE, "info")


def show_theme_picker(app: CodingAgentApp) -> None:
    """Preview themes as the highlight moves; Enter saves one, Esc puts the old one back."""
    entries = theme_entries(app)
    previous: ThemePalette | None = app._palette
    note = OVERRIDE_NOTE if user_theme_path().is_file() else ""

    def chosen(name: str | None) -> None:
        if name is None:
            app.show_theme(previous)
            return
        select_theme(app, name)

    app.push_screen(ThemePickerScreen(entries, app.config.theme, app.show_theme, note), chosen)
