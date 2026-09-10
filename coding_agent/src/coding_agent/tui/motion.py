"""Small, consistent motion primitives for the Textual interface."""

from __future__ import annotations

from textual.geometry import Offset
from textual.widget import Widget


def reveal(
    widget: Widget,
    *,
    duration: float = 0.18,
    offset_y: int = 0,
    delay: float = 0.0,
) -> None:
    """Fade a mounted widget in, optionally lifting it into place.

    Textual runs the animation on its event loop and completes it immediately
    when the application disables full motion.
    """
    from textual._context import NoActiveAppError

    widget.styles.opacity = 0.0
    try:
        widget.styles.animate(
            "opacity",
            1.0,
            duration=duration,
            delay=delay,
            easing="out_cubic",
            level="full",
        )
        if offset_y:
            widget.offset = (0, offset_y)
            widget.animate(
                "offset",
                Offset(0, 0),
                duration=duration,
                delay=delay,
                easing="out_cubic",
                level="full",
            )
    except NoActiveAppError:
        widget.styles.opacity = 1.0


def enter_row(widget: Widget, *, duration: float = 0.16) -> None:
    """Subtle fade-in for a newly mounted transcript row."""
    reveal(widget, duration=duration)


def settle_row(widget: Widget, *, duration: float = 0.12) -> None:
    """Soft settle when a live cell is collected or folded.

    Demand-driven: one opacity animation, and only while the widget is mounted.
    """
    if not widget.is_mounted:
        return
    from textual._context import NoActiveAppError

    widget.styles.opacity = 0.78
    try:
        widget.styles.animate(
            "opacity",
            1.0,
            duration=duration,
            easing="out_cubic",
            level="full",
        )
    except NoActiveAppError:
        widget.styles.opacity = 1.0


__all__ = ["enter_row", "reveal", "settle_row"]
