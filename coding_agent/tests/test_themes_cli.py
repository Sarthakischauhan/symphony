"""``symphony themes`` and the saved ``theme`` setting; the user's own theme.toml still wins."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from coding_agent.addons.plugins import install_plugin
from coding_agent.commands.cli_support import Context
from coding_agent.commands.installed import saved_config
from coding_agent.commands.themes_cli import available_themes, choose_theme, run
from coding_agent.config import DEFAULT_THEME, CodingAgentConfig, symphony_dir, user_theme_path
from coding_agent.tui.theme.active import effective_palette, load_active_theme, selected_palette
from coding_agent.tui.theme.base_palettes import base_palette
from coding_agent.tui.theme.load import load_theme, packaged_theme_path

DRACULA = Path(__file__).parent / "fixtures" / "claude-themes" / "dracula"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    (path / ".git").mkdir(parents=True)
    source = tmp_path / "dracula"
    shutil.copytree(DRACULA, source)
    install_plugin(str(source), cwd=tmp_path)
    return path


def themes(workspace: Path, *argv: str):
    return run(argv, Context(workspace, workspace))


def test_the_default_theme_is_the_default_setting() -> None:
    assert CodingAgentConfig().theme == DEFAULT_THEME == "default"


def test_list_shows_the_default_and_plugin_themes_with_the_current_one_marked(workspace: Path) -> None:
    lines = themes(workspace, "list").text.splitlines()
    assert lines[0].split() == ["THEME", "BASE", "FORMAT", "FILE"]
    rows = {line[2:].split()[0]: line for line in lines[1:] if line.strip()}
    assert rows["default"].startswith("*")
    assert rows["dracula:Dracula"].startswith(" ")
    assert "dracula:Dracula (ANSI)" in "\n".join(lines)


def test_list_without_plugin_themes_says_how_to_get_some(tmp_path: Path) -> None:
    outcome = themes(tmp_path, "list")
    assert "symphony plugins add dracula@claude-themes" in outcome.text


def test_use_saves_the_theme_in_config_and_list_marks_it(workspace: Path) -> None:
    outcome = themes(workspace, "use", "dracula")
    assert outcome.ok and outcome.changed
    assert outcome.text == "Theme set to dracula:Dracula"
    assert saved_config(workspace).theme == "dracula:Dracula"
    assert (symphony_dir() / "config.json").is_file()
    marked = [line for line in themes(workspace, "list").text.splitlines() if line.startswith("*")]
    assert len(marked) == 1 and "dracula:Dracula" in marked[0] and "(ANSI)" not in marked[0]


def test_use_takes_qualified_names_in_any_case_and_back_to_default(workspace: Path) -> None:
    assert choose_theme(workspace, "DRACULA:dracula (ansi)").theme == "dracula:Dracula (ANSI)"
    assert choose_theme(workspace, "Default").theme == DEFAULT_THEME
    assert saved_config(workspace).theme == DEFAULT_THEME


def test_use_an_unknown_theme_is_an_error_and_changes_nothing(workspace: Path) -> None:
    themes(workspace, "use", "dracula")
    outcome = themes(workspace, "use", "nord")
    assert not outcome.ok and not outcome.changed
    assert "no theme named 'nord'" in outcome.text
    assert saved_config(workspace).theme == "dracula:Dracula"


def test_usage_mistakes_are_text_not_exits(workspace: Path) -> None:
    assert not themes(workspace, "use").ok
    assert "list" in themes(workspace, "--help").text


def test_plugins_switched_off_offer_no_themes(workspace: Path) -> None:
    config = saved_config(workspace)
    off = config.model_copy(update={"plugins": config.plugins.model_copy(update={"enabled": False})})
    assert available_themes(workspace, off) == ()


def test_the_chosen_theme_becomes_the_palette_and_default_is_none(workspace: Path) -> None:
    assert selected_palette(saved_config(workspace), workspace) is None
    palette = selected_palette(choose_theme(workspace, "dracula"), workspace)
    assert palette is not None and palette.colors["background"] == "#282a36"


def test_a_theme_that_was_removed_raises_so_the_app_can_fall_back(workspace: Path) -> None:
    config = choose_theme(workspace, "dracula")
    with pytest.raises(ValueError, match="no theme named"):
        selected_palette(config.model_copy(update={"theme": "gone:Theme"}), workspace)


def test_the_chosen_theme_loads_into_the_document(workspace: Path) -> None:
    palette = selected_palette(choose_theme(workspace, "dracula"), workspace)
    document = load_active_theme(palette)
    assert document.colors["background"] == "#282a36"
    assert "#282a36" in document.app_css
    assert document.source == str(packaged_theme_path())


def test_ansi_palette_becomes_terminal_colors_in_css(workspace: Path) -> None:
    palette = selected_palette(choose_theme(workspace, "dracula (ansi)"), workspace)
    document = load_active_theme(palette)
    assert document.colors["accent"] == "color(215)"
    assert document.colors["background"] == base_palette("dark-ansi")["background"] == "default"
    assert "rgb(255,175,95)" in document.app_css
    assert "ansi_default" in document.app_css


def test_the_users_theme_toml_overrides_the_chosen_theme_wholesale(workspace: Path) -> None:
    palette = selected_palette(choose_theme(workspace, "dracula"), workspace)
    user_theme_path().parent.mkdir(parents=True, exist_ok=True)
    user_theme_path().write_text(
        packaged_theme_path().read_text(encoding="utf-8").replace('accent = "#A371F7"', 'accent = "#FF00FF"', 1), encoding="utf-8"
    )
    assert effective_palette(palette) is None
    document = load_active_theme(palette)
    assert Path(document.source) == user_theme_path()
    assert document.colors["accent"] == "#FF00FF"
    assert document.colors["background"] == load_theme(packaged_theme_path()).colors["background"]


def test_the_user_theme_path_follows_symphony_home() -> None:
    assert user_theme_path() == symphony_dir() / "theme.toml"
    assert Path(os.environ["SYMPHONY_HOME"]) == symphony_dir()


def test_symphony_themes_runs_without_loading_the_tui(workspace: Path) -> None:
    script = (
        "import sys\nfrom coding_agent.commands.themes_cli import main\n"
        "code = main(['list'])\n"
        "print(','.join(sorted(n for n in sys.modules if n == 'textual' or n.startswith(('textual.', 'coding_agent.tui')))))\n"
        "raise SystemExit(code)\n"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, cwd=workspace, env=dict(os.environ))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[-1] == ""
    assert "dracula:Dracula" in done.stdout
