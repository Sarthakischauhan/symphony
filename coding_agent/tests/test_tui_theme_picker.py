"""``/theme`` in the TUI: live preview, keep, cancel, direct switch, and restoring the saved theme at start."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Iterator

import pytest
from textual.pilot import Pilot
from textual.widgets import OptionList

from coding_agent.addons.plugins import install_plugin, remove_plugin
from coding_agent.commands.installed import saved_config
from coding_agent.commands.themes_cli import choose_theme
from coding_agent.config import user_theme_path
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.chrome import TopBar
from coding_agent.tui.screens.theme_picker import ThemePickerScreen
from coding_agent.tui.theme import SYMPHONY_COLORS
from coding_agent.tui.theme.active import publish_theme
from coding_agent.tui.theme.load import load_theme, packaged_theme_path

DRACULA = Path(__file__).parent / "fixtures" / "claude-themes" / "dracula"
DEFAULT_BACKGROUND = "#0A0A0A"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "work"
    (path / ".git").mkdir(parents=True)
    source = tmp_path / "dracula"
    shutil.copytree(DRACULA, source)
    install_plugin(str(source), cwd=tmp_path)
    yield path
    publish_theme(load_theme(packaged_theme_path()))


def drive(workspace: Path, scenario: Callable[[CodingAgentApp, Pilot[None]], Awaitable[None]]) -> None:
    app = CodingAgentApp(workspace=workspace)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(run())


def picker(app: CodingAgentApp) -> ThemePickerScreen:
    assert isinstance(app.screen, ThemePickerScreen)
    return app.screen


def test_the_picker_lists_default_and_plugin_themes_and_marks_the_current_one(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme")
        await pilot.pause()
        options = picker(app).query_one("#theme-list", OptionList)
        prompts = [str(options.get_option_at_index(index).prompt) for index in range(options.option_count)]
        assert [text.split()[1] for text in prompts[:2]] == ["default", "dracula:Dracula"]
        assert prompts[0].startswith("●") and prompts[1].startswith("○")
        assert options.highlighted == 0

    drive(workspace, scenario)


def test_moving_the_highlight_previews_the_theme_and_escape_restores_the_old_one(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert SYMPHONY_COLORS["background"] == "#282a36"
        assert app.ansi_color is False
        pane = picker(app).query_one("#theme-pane")
        assert pane.styles.background.hex == "#44475A"
        await pilot.press("down")
        await pilot.pause()
        assert app.ansi_color is True
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ThemePickerScreen)
        assert SYMPHONY_COLORS["background"] == DEFAULT_BACKGROUND
        assert app.ansi_color is False
        assert saved_config(workspace).theme == "default"

    drive(workspace, scenario)


def test_topbar_recolors_immediately_on_preview_and_cancel(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        topbar = app.query_one(TopBar)
        topbar.set_context(workspace, "provider:model")
        assert topbar._model_text(80).spans[-1].style == "bold " + SYMPHONY_COLORS["accent"]
        await app._command_manager.run("/theme")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert SYMPHONY_COLORS["accent"] == "#ffb86c"
        assert topbar.content.columns[1]._cells[0].spans[-1].style == "bold #ffb86c"
        await pilot.press("escape")
        await pilot.pause()
        assert topbar.content.columns[1]._cells[0].spans[-1].style == "bold " + SYMPHONY_COLORS["accent"]

    drive(workspace, scenario)


def test_enter_keeps_the_previewed_theme_and_saves_it(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme")
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert not isinstance(app.screen, ThemePickerScreen)
        assert SYMPHONY_COLORS["background"] == "#282a36"
        assert app.config.theme == "dracula:Dracula"
        assert saved_config(workspace).theme == "dracula:Dracula"

    drive(workspace, scenario)


def test_theme_with_a_name_switches_without_the_picker(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme dracula")
        await pilot.pause()
        assert not isinstance(app.screen, ThemePickerScreen)
        assert SYMPHONY_COLORS["background"] == "#282a36"
        assert saved_config(workspace).theme == "dracula:Dracula"
        await app._command_manager.run("/theme default")
        await pilot.pause()
        assert SYMPHONY_COLORS["background"] == DEFAULT_BACKGROUND
        assert saved_config(workspace).theme == "default"

    drive(workspace, scenario)


def test_an_unknown_theme_name_keeps_the_current_theme(workspace: Path) -> None:
    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme nord")
        await pilot.pause()
        assert SYMPHONY_COLORS["background"] == DEFAULT_BACKGROUND
        assert saved_config(workspace).theme == "default"

    drive(workspace, scenario)


def test_the_saved_theme_applies_when_the_app_starts(workspace: Path) -> None:
    choose_theme(workspace, "dracula")

    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        assert SYMPHONY_COLORS["background"] == "#282a36"
        assert app.config.theme == "dracula:Dracula"

    drive(workspace, scenario)


def test_a_saved_theme_that_no_longer_exists_falls_back_to_the_default(workspace: Path) -> None:
    choose_theme(workspace, "dracula")
    remove_plugin("dracula", workspace)

    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        assert SYMPHONY_COLORS["background"] == DEFAULT_BACKGROUND

    drive(workspace, scenario)


def test_the_users_theme_toml_wins_over_the_picked_theme_and_the_picker_says_so(workspace: Path) -> None:
    user_theme_path().parent.mkdir(parents=True, exist_ok=True)
    user_theme_path().write_text(packaged_theme_path().read_text(encoding="utf-8"), encoding="utf-8")

    async def scenario(app: CodingAgentApp, pilot: Pilot[None]) -> None:
        await app._command_manager.run("/theme")
        await pilot.pause()
        assert "overrides every theme" in str(picker(app).query_one("#theme-title").content)
        await pilot.press("down")
        await pilot.pause()
        assert SYMPHONY_COLORS["background"] == DEFAULT_BACKGROUND

    drive(workspace, scenario)
