"""Subtle enter animations for the coding-agent TUI.

Transcript cards reveal with a left-to-right opacity wipe. Composite
widgets (tools, reasoning, menus, modals) fade in so presentation demos
feel alive without slowing ordinary use.

Animations honor ``app.animation_level``: they run at ``basic`` and
``full``, and are skipped when the level is ``none``.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style

from textual.color import Color
from textual.geometry import Offset, Region
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget


WIPE_DURATION = 0.32
FADE_DURATION = 0.22
MENU_DURATION = 0.16
MODAL_DURATION = 0.24
WIPE_SOFTNESS = 0.36
SLIDE_CELLS = 2
SCREEN_BACKGROUND = Color(10, 10, 10)
DEFAULT_FOREGROUND = Color(237, 237, 237)


def animations_enabled(widget: Widget) -> bool:
    """Return whether this widget's app is allowed to play enter animations."""
    try:
        return widget.app.animation_level != "none"
    except Exception:
        return False


def wipe_alpha(
    x: int,
    width: int,
    progress: float,
    softness: float = WIPE_SOFTNESS,
) -> float:
    """Opacity of column ``x`` during a left-to-right wipe.

    ``progress`` 0 is fully hidden, 1 is fully revealed. ``softness`` is the
    fraction of the widget width used as the leading fade edge.
    """
    if width <= 0:
        return 1.0
    if progress <= 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    soft = max(softness, 1.0 / width)
    t = (progress * (1.0 + soft) - (x / width)) / soft
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def apply_horizontal_wipe(
    strip: Strip,
    progress: float,
    *,
    softness: float = WIPE_SOFTNESS,
    background: Color | None = None,
    origin_x: int = 0,
    widget_width: int | None = None,
) -> Strip:
    """Blend a rendered line so it reveals from left to right."""
    progress = max(0.0, min(1.0, progress))
    cell_width = strip.cell_length
    if cell_width <= 0:
        return strip
    span = widget_width if widget_width and widget_width > 0 else origin_x + cell_width
    if progress >= 0.999:
        return strip
    if progress <= 0.001:
        return Strip.blank(cell_width)

    bg = background or SCREEN_BACKGROUND
    out: list[Segment] = []
    x = origin_x
    for text, style, control in strip._segments:
        if control:
            out.append(Segment(text, style, control))
            continue
        remaining = text
        while remaining:
            cell, remaining = _split_first_cell(remaining)
            width = cell_len(cell) or 1
            alpha = wipe_alpha(x, span, progress, softness)
            out.append(_fade_cell(cell, style, bg, alpha, width))
            x += width
    return Strip(out, cell_width)


def play_wipe_enter(
    widget: Widget,
    *,
    duration: float = WIPE_DURATION,
) -> None:
    """Start a left-to-right wipe on a widget that exposes ``wipe_progress``."""
    if not hasattr(widget, "wipe_progress"):
        return
    if not animations_enabled(widget):
        setattr(widget, "wipe_progress", 1.0)
        return
    setattr(widget, "wipe_progress", 0.0)
    widget.animate(
        "wipe_progress",
        1.0,
        duration=duration,
        easing="out_cubic",
        level="basic",
    )


def play_fade_enter(
    widget: Widget,
    *,
    duration: float = FADE_DURATION,
    slide: int = SLIDE_CELLS,
) -> None:
    """Fade a composite widget in, with a short left-to-right slide."""
    if not animations_enabled(widget):
        widget.styles.opacity = 1.0
        widget.offset = Offset(0, 0)
        return
    widget.styles.opacity = 0.0
    widget.offset = Offset(-slide, 0)
    widget.styles.animate(
        "opacity",
        1.0,
        duration=duration,
        easing="out_cubic",
        level="basic",
    )
    widget.animate(
        "offset",
        Offset(0, 0),
        duration=duration,
        easing="out_cubic",
        level="basic",
    )


def wipe_background(widget: Widget) -> Color:
    """Background to blend wiped cells into."""
    try:
        background = widget.visual_style.background
    except Exception:
        return SCREEN_BACKGROUND
    if background is None or background.is_transparent:
        return SCREEN_BACKGROUND
    return background


class EnterAnimated:
    """Mixin that wipes a leaf widget in from the left on mount.

    Must be combined with a Textual ``Widget`` subclass. Place it first in
    the MRO so ``render_lines`` and ``on_mount`` wrap the base widget.
    """

    wipe_progress: reactive[float] = reactive(1.0)

    def on_mount(self) -> None:
        play_wipe_enter(self)  # type: ignore[arg-type]

    def render_lines(self, crop: Region) -> list[Strip]:
        strips: list[Strip] = super().render_lines(crop)  # type: ignore[misc]
        progress = self.wipe_progress
        if progress >= 0.999:
            return strips
        background = wipe_background(self)  # type: ignore[arg-type]
        width = self.size.width  # type: ignore[attr-defined]
        return [
            apply_horizontal_wipe(
                strip,
                progress,
                background=background,
                origin_x=crop.x,
                widget_width=width,
            )
            for strip in strips
        ]


def _split_first_cell(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    for index in range(1, len(text) + 1):
        if cell_len(text[:index]) >= 1:
            return text[:index], text[index:]
    return text, ""


def _fade_cell(
    text: str,
    style: Style | None,
    background: Color,
    opacity: float,
    width: int,
) -> Segment:
    if opacity <= 0.02:
        return Segment(" " * width)
    cell_style = style if style is not None else Style()
    if opacity >= 0.98:
        return Segment(text, cell_style)
    faded = cell_style
    foreground = (
        Color.from_rich_color(cell_style.color)
        if cell_style.color is not None
        else DEFAULT_FOREGROUND
    )
    faded += Style.from_color(color=background.blend(foreground, opacity).rich_color)
    if cell_style.bgcolor is not None:
        cell_background = Color.from_rich_color(cell_style.bgcolor)
        faded += Style.from_color(
            bgcolor=background.blend(cell_background, opacity).rich_color
        )
    return Segment(text, faded)
