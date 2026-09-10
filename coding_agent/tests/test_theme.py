"""Theme.toml loader: home path, packaged default, and public exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tui.theme import APP_CSS, SYMPHONY_COLORS, themed_markdown
from coding_agent.tui.theme.load import (
    SYMPHONY_COLOR_KEYS,
    ThemeConfigError,
    load_theme,
    packaged_theme_path,
    user_theme_path,
)


def test_default_theme_toml_loads() -> None:
    theme = load_theme()
    assert Path(theme.source).is_file()
    assert theme.source == str(packaged_theme_path())
    assert theme.colors["background"] == "#0A0A0A"
    assert theme.colors["accent"] == "#A371F7"


def test_required_color_keys_present() -> None:
    theme = load_theme(packaged_theme_path())
    assert tuple(theme.colors) == SYMPHONY_COLOR_KEYS
    for key in SYMPHONY_COLOR_KEYS:
        assert theme.colors[key].startswith("#")


def test_app_css_includes_accent_and_background() -> None:
    theme = load_theme(packaged_theme_path())
    assert theme.app_css.strip()
    assert theme.colors["background"] in theme.app_css
    assert theme.colors["accent"] in theme.app_css
    assert APP_CSS.strip()
    assert SYMPHONY_COLORS["background"] in APP_CSS
    assert SYMPHONY_COLORS["accent"] in APP_CSS
    assert SYMPHONY_COLORS["background"] == theme.colors["background"]
    assert SYMPHONY_COLORS["accent"] == theme.colors["accent"]


def test_home_theme_overrides_packaged_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    home_theme = user_theme_path()
    assert home_theme == tmp_path / ".symphony" / "theme.toml"
    assert home_theme == Path.home() / ".symphony" / "theme.toml"
    home_theme.parent.mkdir(parents=True)
    home_theme.write_text(
        packaged_theme_path()
        .read_text(encoding="utf-8")
        .replace('accent = "#A371F7"', 'accent = "#FF00FF"', 1),
        encoding="utf-8",
    )
    theme = load_theme()
    assert Path(theme.source) == home_theme
    assert theme.colors["accent"] == "#FF00FF"
    assert "#FF00FF" in theme.app_css
    assert theme.colors["background"] == "#0A0A0A"


def test_composed_surfaces_include_section_markers() -> None:
    theme = load_theme(packaged_theme_path())
    assert "Screen {" in theme.chrome_css
    assert ".tool-call {" in theme.tools_css
    assert "#composer {" in theme.composer_css
    assert "ResumeApp {" in theme.resume_css
    assert "OnboardApp {" in theme.onboard_css
    assert theme.onboard_css.startswith(theme.resume_css)
    assert "ContentModal {" in theme.content_modal_css
    assert theme.content_modal_css.startswith(theme.modal_base_css)
    assert "ProviderOnboardScreen {" in theme.provider_modal_css


def test_missing_color_token_raises(tmp_path: Path) -> None:
    broken = tmp_path / "theme.toml"
    broken.write_text(
        packaged_theme_path()
        .read_text(encoding="utf-8")
        .replace("background = ", "canvas = ", 1),
        encoding="utf-8",
    )
    with pytest.raises(ThemeConfigError, match="background"):
        load_theme(broken)


def test_themed_markdown_uses_loaded_palette() -> None:
    rendered = themed_markdown("hello")
    assert rendered.markup == "hello"
