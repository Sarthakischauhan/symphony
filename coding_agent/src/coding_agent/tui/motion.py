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
    widget.styles.opacity = 0.0
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


__all__ = ["reveal"]
