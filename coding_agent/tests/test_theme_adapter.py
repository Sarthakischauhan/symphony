"""Claude theme -> Symphony palette: color syntax, the slot table, base fallback, syntax colors."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pygments.token import Comment, Keyword, Name, String
from rich.style import Style

from coding_agent.addons.plugins import PluginTheme
from coding_agent.addons.plugins.themes import Base, discover_plugin_themes
from coding_agent.tui.theme.ansi_colors import parse_theme_color, textual_color
from coding_agent.tui.theme.base_palettes import ANSI_BASES, base_palette
from coding_agent.tui.theme.claude_slots import SYNTAX_MAPPINGS, UI_MAPPINGS
from coding_agent.tui.theme.load import OPTIONAL_COLOR_KEYS, SYMPHONY_COLOR_KEYS, load_theme, packaged_theme_path
from coding_agent.tui.theme.plugin_palette import palette_for
from coding_agent.tui.theme.style import PaletteSyntaxTheme

DRACULA = Path(__file__).parent / "fixtures" / "claude-themes" / "dracula"
ALL_KEYS = (*SYMPHONY_COLOR_KEYS, *OPTIONAL_COLOR_KEYS)


def claude(overrides: dict[str, str], base: str = "dark") -> PluginTheme:
    return PluginTheme("t", "T", Path("t.json"), "claude", cast(Base, base), overrides)


def native(colors: dict[str, str], base: str = "dark") -> PluginTheme:
    return PluginTheme("t", "T", Path("t.toml"), "symphony", cast(Base, base), colors)


def foreground(style: Style) -> str:
    assert style.color is not None
    return style.color.name


def background(style: Style) -> str:
    assert style.bgcolor is not None
    return style.bgcolor.name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#FF8800", "#ff8800"),
        ("#f80", "#ff8800"),
        ("rgb(255, 184,108)", "#ffb86c"),
        ("ansi:red", "red"),
        ("ansi:blackBright", "bright_black"),
        ("ansi:whiteBright", "bright_white"),
        ("ansi256(215)", "color(215)"),
        ("ansi256(0)", "color(0)"),
        ("ansi256(255)", "color(255)"),
    ],
)
def test_theme_color_syntax_becomes_a_rich_color(value: str, expected: str) -> None:
    assert parse_theme_color(value) == expected


@pytest.mark.parametrize("value", ["", "red", "ansi:orange", "ansi:orangeBright", "ansi256(256)", "rgb(256,0,0)", "#12345", "#gg0000", "ansi256(x)"])
def test_invalid_theme_colors_are_rejected(value: str) -> None:
    assert parse_theme_color(value) is None


def test_textual_colors_keep_the_terminal_palette_for_the_sixteen_ansi_colors() -> None:
    assert textual_color("#ff8800") == "#ff8800"
    assert textual_color("red") == "ansi_red"
    assert textual_color("bright_black") == "ansi_bright_black"
    assert textual_color("default") == "ansi_default"


def test_textual_colors_turn_the_extended_256_palette_into_rgb() -> None:
    assert textual_color("color(215)") == "rgb(255,175,95)"
    assert textual_color("color(5)") == "ansi_magenta"
    with pytest.raises(ValueError, match="not a color"):
        textual_color("nonsense")


def test_every_mapping_targets_a_known_token_and_each_token_has_one_row() -> None:
    tokens = [mapping.token for mapping in UI_MAPPINGS + SYNTAX_MAPPINGS]
    assert set(tokens) <= set(ALL_KEYS)
    assert len(tokens) == len(set(tokens))


def test_the_slot_table_maps_claude_slots_to_symphony_tokens() -> None:
    slots = {
        "text": "#010101", "subtle": "#020202", "inactive": "#030303", "promptBorder": "#040404", "claude": "#050505",
        "success": "#060606", "error": "#070707", "warning": "#080808", "diffAdded": "#090909", "diffRemoved": "#0a0a0a",
        "selectionBg": "#0b0b0b", "userMessageBackground": "#0c0c0c", "clawd_background": "#0d0d0d",
    }
    colors = palette_for(claude(slots)).colors
    assert {key: colors[key] for key in ("foreground", "muted", "muted_dim", "edge", "accent", "string", "keyword", "number")} == {
        "foreground": "#010101", "muted": "#020202", "muted_dim": "#030303", "edge": "#040404",
        "accent": "#050505", "string": "#060606", "keyword": "#070707", "number": "#080808",
    }
    assert colors["type_keywords"] == "#070707"
    assert (colors["diff_added"], colors["diff_removed"]) == ("#090909", "#0a0a0a")
    assert (colors["overlay"], colors["surface"], colors["background"]) == ("#0b0b0b", "#0c0c0c", "#0d0d0d")


def test_the_background_slot_is_a_task_accent_and_never_fills_the_screen() -> None:
    colors = palette_for(claude({"background": "#00ffff", "clawd_background": "#101010"})).colors
    assert colors["background"] == "#101010"
    assert "#00ffff" not in colors.values()
    unset = palette_for(claude({"background": "#00ffff"})).colors
    assert unset["background"] == base_palette("dark")["background"]


def test_unset_and_invalid_slots_fall_back_to_the_base_palette() -> None:
    palette = palette_for(claude({"claude": "not a color", "text": "ansi:nope", "success": "#00ff00"}))
    dark = base_palette("dark")
    assert palette.colors["accent"] == dark["accent"]
    assert palette.colors["foreground"] == dark["foreground"]
    assert palette.colors["string"] == "#00ff00"
    assert set(palette.colors) == set(dark)
    assert palette.ansi is False


@pytest.mark.parametrize("base", ["dark", "light", "dark-daltonized", "light-daltonized", "dark-ansi", "light-ansi"])
def test_each_base_gives_a_complete_palette(base: str) -> None:
    colors = base_palette(base)
    assert set(ALL_KEYS) <= set(colors)
    assert palette_for(claude({}, base)).colors == colors


def test_dark_is_the_packaged_palette_and_daltonized_bases_reuse_dark_or_light() -> None:
    packaged = load_theme(packaged_theme_path()).colors
    assert base_palette("dark") == packaged
    assert base_palette("dark-daltonized") == packaged
    assert base_palette("light-daltonized") == base_palette("light")
    assert base_palette("light")["background"] != packaged["background"]


def test_base_palettes_are_copies() -> None:
    base_palette("dark")["accent"] = "#000000"
    assert base_palette("dark")["accent"] != "#000000"


def test_ansi_bases_use_terminal_colors_only() -> None:
    for base in ANSI_BASES:
        for key, value in base_palette(base).items():
            assert not value.startswith("#"), (base, key, value)
            textual_color(value)


def test_ansi_themes_leave_the_background_and_syntax_to_the_terminal() -> None:
    slots = {"clawd_background": "ansi256(235)", "blue_FOR_SUBAGENTS_ONLY": "ansi:blue", "text": "ansi:white", "claude": "ansi256(215)"}
    palette = palette_for(claude(slots, "dark-ansi"))
    ansi = base_palette("dark-ansi")
    assert palette.ansi is True
    assert palette.colors["background"] == ansi["background"] == "default"
    assert palette.colors["function"] == ansi["function"]
    assert palette.colors["foreground"] == "white"
    assert palette.colors["accent"] == "color(215)"


def test_regular_themes_derive_syntax_colors_from_their_palette() -> None:
    slots = {
        "text": "#111111", "subtle": "#222222", "blue_FOR_SUBAGENTS_ONLY": "#0000ff", "yellow_FOR_SUBAGENTS_ONLY": "#ffff00",
        "cyan_FOR_SUBAGENTS_ONLY": "#00ffff", "purple_FOR_SUBAGENTS_ONLY": "#800080", "orange_FOR_SUBAGENTS_ONLY": "#ffa500",
        "pink_FOR_SUBAGENTS_ONLY": "#ffc0cb", "rainbow_blue": "#123456",
    }
    colors = palette_for(claude(slots)).colors
    assert colors["variable"] == "#111111"
    assert colors["comment"] == colors["punctuation"] == "#222222"
    assert {key: colors[key] for key in ("function", "type", "tag", "attribute", "constant", "operator")} == {
        "function": "#0000ff", "type": "#ffff00", "tag": "#00ffff", "attribute": "#800080", "constant": "#ffa500", "operator": "#ffc0cb",
    }


def test_a_missing_subagent_slot_falls_through_to_the_rainbow_then_the_base() -> None:
    colors = palette_for(claude({"rainbow_blue": "#123456"})).colors
    assert colors["function"] == "#123456"
    assert colors["type"] == base_palette("dark")["type"]


def test_native_themes_overlay_known_tokens_with_valid_colors_only() -> None:
    palette = palette_for(native({"accent": "#82AAFF", "muted": "ansi:red", "bogus": "#ffffff", "edge": "nope"}, "light"))
    light = base_palette("light")
    assert palette.colors["accent"] == "#82aaff"
    assert palette.colors["muted"] == "red"
    assert "bogus" not in palette.colors
    assert palette.colors["edge"] == light["edge"]
    assert palette.ansi is False
    assert palette.name == "t:T"


def test_dracula_maps_to_its_own_palette_and_the_ansi_variant_to_the_terminal() -> None:
    themes = {item.name: item for item in discover_plugin_themes("dracula", DRACULA)[0]}
    colors = palette_for(themes["Dracula"]).colors
    assert (colors["background"], colors["foreground"], colors["accent"]) == ("#282a36", "#f8f8f2", "#ffb86c")
    assert colors["edge"] == "#bd93f9"
    ansi = palette_for(themes["Dracula (ANSI)"])
    assert ansi.ansi and ansi.colors["background"] == "default"
    assert all(not value.startswith("#") for value in ansi.colors.values())


def test_the_palette_syntax_theme_styles_tokens_from_the_palette() -> None:
    colors = base_palette("dark") | {"keyword": "#ff0000", "string": "#00ff00", "comment": "#777777", "background": "#101010"}
    theme = PaletteSyntaxTheme(colors)
    assert foreground(theme.get_style_for_token(Keyword)) == "#ff0000"
    assert foreground(theme.get_style_for_token(String.Double)) == "#00ff00"
    assert foreground(theme.get_style_for_token(Comment.Single)) == "#777777"
    assert theme.get_style_for_token(Name).color is not None
    assert background(theme.get_background_style()) == "#101010"


def test_the_palette_syntax_theme_can_use_terminal_colors() -> None:
    theme = PaletteSyntaxTheme(base_palette("dark-ansi"))
    assert foreground(theme.get_style_for_token(Keyword)) == "red"
    assert background(theme.get_background_style()) == "default"
