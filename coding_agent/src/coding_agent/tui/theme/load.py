"""Load the Symphony TUI theme from ~/.symphony/theme.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

THEME_FILE = "theme.toml"
PACKAGE_NAME = "coding_agent.tui.theme"

SYMPHONY_COLOR_KEYS = (
    "background",
    "foreground",
    "accent",
    "muted",
    "muted_dim",
    "edge",
    "comment",
    "keyword",
    "type_keywords",
    "string",
    "function",
    "variable",
    "number",
    "operator",
    "punctuation",
    "type",
    "tag",
    "attribute",
    "constant",
    "surface",
    "overlay",
    "subtext",
)

CSS_SECTIONS = ("chrome", "tools", "composer", "resume", "onboard")
MODAL_SECTIONS = (
    "base",
    "content",
    "image",
    "diff",
    "extensions",
    "learning",
    "plan",
    "context",
    "provider",
)


class ThemeConfigError(ValueError):
    """theme.toml is missing a required table, key, or color token."""


@dataclass(frozen=True)
class ThemeDocument:
    """Parsed theme.toml plus the assembled CSS strings the TUI imports."""

    source: str
    colors: dict[str, str]
    chrome_css: str
    tools_css: str
    composer_css: str
    resume_css: str
    onboard_css: str
    modal_base_css: str
    content_modal_css: str
    image_modal_css: str
    diff_modal_css: str
    extensions_modal_css: str
    learning_modal_css: str
    plan_modal_css: str
    context_modal_css: str
    provider_modal_css: str

    @property
    def app_css(self) -> str:
        return glue_css(glue_css(self.chrome_css, self.tools_css), self.composer_css)


def user_theme_path() -> Path:
    """Runtime theme file: ~/.symphony/theme.toml."""
    return Path.home() / ".symphony" / THEME_FILE


def packaged_theme_path() -> Path:
    """Filesystem path of the theme.toml shipped next to this package."""
    return Path(__file__).with_name(THEME_FILE)


def resolve_theme_path(path: Path | None = None) -> Path:
    """Prefer an explicit path, then ~/.symphony/theme.toml, then the package copy."""
    if path is not None:
        resolved = Path(path)
        if not resolved.is_file():
            raise ThemeConfigError(f"theme file not found: {resolved}")
        return resolved
    user = user_theme_path()
    if user.is_file():
        return user
    packaged = packaged_theme_path()
    if packaged.is_file():
        return packaged
    raise ThemeConfigError(
        "theme.toml not found (no packaged copy and no ~/.symphony/theme.toml)"
    )


def load_theme(path: Path | None = None) -> ThemeDocument:
    """Parse theme.toml and assemble the public color/CSS surface."""
    source, raw = _read_theme(path)
    document = _parse_toml(source, raw)
    colors = color_tokens(document)
    css = _table(document, "css", source=source)
    variables = _string_table(_table(css, "variables", source=source, label="css.variables"))
    sections = {name: _css_string(css, name, source=source) for name in CSS_SECTIONS}
    modal = _table(css, "modal", source=source, label="css.modal")
    modal_css = {name: _css_string(modal, name, source=source, label=f"css.modal.{name}") for name in MODAL_SECTIONS}
    chrome = textual_variable_block(colors, variables) + sections["chrome"]
    base = modal_css["base"]
    return ThemeDocument(
        source=source,
        colors={key: colors[key] for key in SYMPHONY_COLOR_KEYS},
        chrome_css=chrome,
        tools_css=sections["tools"],
        composer_css=sections["composer"],
        resume_css=sections["resume"],
        onboard_css=glue_css(sections["resume"], sections["onboard"]),
        modal_base_css=base,
        content_modal_css=glue_css(base, modal_css["content"]),
        image_modal_css=glue_css(base, modal_css["image"]),
        diff_modal_css=glue_css(base, modal_css["diff"]),
        extensions_modal_css=glue_css(base, modal_css["extensions"]),
        learning_modal_css=glue_css(base, modal_css["learning"]),
        plan_modal_css=glue_css(base, modal_css["plan"]),
        context_modal_css=glue_css(base, modal_css["context"]),
        provider_modal_css=glue_css(base, modal_css["provider"]),
    )


def glue_css(prefix: str, extra: str) -> str:
    """Join two CSS fragments with a blank line, matching the old Python constants."""
    if extra.startswith("\n"):
        return prefix + extra
    if prefix.endswith("\n\n"):
        return prefix + extra
    if prefix.endswith("\n"):
        return prefix + "\n" + extra
    return prefix + "\n\n" + extra


def color_tokens(document: Mapping[str, Any]) -> dict[str, str]:
    """Return every [colors] entry; required Symphony tokens must be present."""
    colors = _string_table(_table(document, "colors"))
    missing = [key for key in SYMPHONY_COLOR_KEYS if key not in colors]
    if missing:
        raise ThemeConfigError("theme.toml [colors] missing: " + ", ".join(missing))
    return colors


def textual_variable_block(colors: Mapping[str, str], variables: Mapping[str, str]) -> str:
    """Render Textual `$name: value;` declarations from [css.variables]."""
    if not variables:
        raise ThemeConfigError("theme.toml [css.variables] is empty")
    lines = ["/* Symphony dark theme. Palette tokens live in theme.toml. */"]
    for name, token in variables.items():
        if token not in colors:
            raise ThemeConfigError(f"[css.variables].{name} refers to unknown color {token!r}")
        lines.append(f"${name}: {colors[token]};")
    return "\n".join(lines) + "\n\n"


def _read_theme(path: Path | None) -> tuple[str, str]:
    if path is not None or user_theme_path().is_file() or packaged_theme_path().is_file():
        resolved = resolve_theme_path(path)
        return str(resolved), resolved.read_text(encoding="utf-8")
    resource = files(PACKAGE_NAME).joinpath(THEME_FILE)
    return f"package:{THEME_FILE}", resource.read_text(encoding="utf-8")


def _parse_toml(source: str, raw: str) -> dict[str, Any]:
    try:
        document = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ThemeConfigError(f"invalid TOML in {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ThemeConfigError(f"{source} must be a TOML table")
    return document


def _table(
    document: Mapping[str, Any],
    key: str,
    *,
    source: str = "theme.toml",
    label: str | None = None,
) -> dict[str, Any]:
    name = label or key
    value = document.get(key)
    if not isinstance(value, dict):
        raise ThemeConfigError(f"{source} is missing [{name}]")
    return value


def _string_table(table: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in table.items():
        if not isinstance(value, str) or not value:
            raise ThemeConfigError(f"theme.toml {key!r} must be a non-empty string")
        values[str(key)] = value
    return values


def _css_string(
    table: Mapping[str, Any],
    key: str,
    *,
    source: str,
    label: str | None = None,
) -> str:
    name = label or f"css.{key}"
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ThemeConfigError(f"{source} is missing a non-empty [{name}] string")
    return value


_DEFAULT = load_theme()

SYMPHONY_COLORS = _DEFAULT.colors
CHROME_CSS = _DEFAULT.chrome_css
TOOLS_CSS = _DEFAULT.tools_css
COMPOSER_CSS = _DEFAULT.composer_css
RESUME_CSS = _DEFAULT.resume_css
ONBOARD_CSS = _DEFAULT.onboard_css
MODAL_BASE_CSS = _DEFAULT.modal_base_css
CONTENT_MODAL_CSS = _DEFAULT.content_modal_css
IMAGE_MODAL_CSS = _DEFAULT.image_modal_css
DIFF_MODAL_CSS = _DEFAULT.diff_modal_css
EXTENSIONS_MODAL_CSS = _DEFAULT.extensions_modal_css
LEARNING_MODAL_CSS = _DEFAULT.learning_modal_css
PLAN_MODAL_CSS = _DEFAULT.plan_modal_css
CONTEXT_MODAL_CSS = _DEFAULT.context_modal_css
PROVIDER_MODAL_CSS = _DEFAULT.provider_modal_css
APP_CSS = _DEFAULT.app_css
