"""Theme.toml loader: tokens, APP_CSS, and the packaged default copy."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tui.theme import APP_CSS, SYMPHONY_COLORS, themed_markdown
from coding_agent.tui.theme.load import (
    SYMPHONY_COLOR_KEYS,
    ThemeConfigError,
    find_repo_theme,
    load_theme,
    packaged_theme_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_THEME = REPO_ROOT / "config" / "theme.toml"


def test_default_theme_toml_loads() -> None:
    theme = load_theme()
    assert Path(theme.source).is_file()
    assert theme.colors["background"] == "#0A0A0A"
    assert theme.colors["accent"] == "#A371F7"


def test_required_color_keys_present() -> None:
    theme = load_theme(REPO_THEME)
    assert tuple(theme.colors) == SYMPHONY_COLOR_KEYS
    for key in SYMPHONY_COLOR_KEYS:
        assert theme.colors[key].startswith("#")


def test_app_css_includes_accent_and_background() -> None:
    theme = load_theme(REPO_THEME)
    assert theme.app_css.strip()
    assert theme.colors["background"] in theme.app_css
    assert theme.colors["accent"] in theme.app_css
    assert APP_CSS == theme.app_css
    assert SYMPHONY_COLORS["background"] == theme.colors["background"]
    assert SYMPHONY_COLORS["accent"] == theme.colors["accent"]


def test_packaged_theme_matches_repo_source() -> None:
    packaged = packaged_theme_path()
    assert packaged.is_file()
    assert REPO_THEME.is_file()
    assert packaged.read_text(encoding="utf-8") == REPO_THEME.read_text(encoding="utf-8")
    repo = find_repo_theme()
    assert repo == REPO_THEME


def test_composed_surfaces_include_section_markers() -> None:
    theme = load_theme(REPO_THEME)
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
        REPO_THEME.read_text(encoding="utf-8").replace("background = ", "canvas = ", 1),
        encoding="utf-8",
    )
    with pytest.raises(ThemeConfigError, match="background"):
        load_theme(broken)


def test_themed_markdown_uses_loaded_palette() -> None:
    rendered = themed_markdown("hello")
    assert rendered.markup == "hello"
