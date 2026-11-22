"""Which theme is in effect, and publishing it to the running TUI.

Precedence, highest first: the user's own ``theme.toml`` in the Symphony home, the
theme chosen with ``/theme`` or ``symphony themes use`` (saved as ``theme`` in
config.json), then the packaged default.
"""

from __future__ import annotations

from pathlib import Path

from coding_agent.addons.plugins import find_theme
from coding_agent.commands.themes_cli import available_themes
from coding_agent.config import DEFAULT_THEME, CodingAgentConfig
from coding_agent.tui.theme.load import ThemeDocument, apply_theme, load_theme, user_theme_path
from coding_agent.tui.theme.plugin_palette import ThemePalette, palette_for
from coding_agent.tui.theme.style import restyle


def selected_palette(config: CodingAgentConfig, workspace: Path) -> ThemePalette | None:
    """The palette of the theme ``config`` chose; None for the default. ``ValueError`` when it no longer exists."""
    if config.theme == DEFAULT_THEME:
        return None
    return palette_for(find_theme(available_themes(workspace, config), config.theme))


def effective_palette(palette: ThemePalette | None) -> ThemePalette | None:
    """``palette`` unless the user's own theme.toml overrides it."""
    return None if user_theme_path().is_file() else palette


def load_active_theme(palette: ThemePalette | None) -> ThemeDocument:
    """The document to show for the chosen ``palette``, after the user's theme.toml has its say."""
    effective = effective_palette(palette)
    return load_theme() if effective is None else load_theme(palette=effective.colors)


def publish_theme(document: ThemeDocument) -> None:
    """Make ``document`` the theme the TUI's shared color tables, syntax and Markdown styles read."""
    apply_theme(document)
    restyle()


__all__ = ["effective_palette", "load_active_theme", "publish_theme", "selected_palette"]
