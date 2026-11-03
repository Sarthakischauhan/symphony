"""Name the terminal tab "Symphony" while the TUI runs, then put the old title back.

The terminal appends the working directory itself (``Symphony ~/projects/x``),
so the title carries no path.
"""

from __future__ import annotations

PUSH_TITLE = "\x1b[22;0t"
SET_TITLE = "\x1b]0;Symphony\x07"
POP_TITLE = "\x1b[23;0t"


class TerminalTitleSurface:
    """App mixin: push the current title and set ours on mount, pop it on exit.

    Textual runs every ``on_mount``/``on_unmount`` along the class hierarchy,
    so these add to the app's own handlers. They write through the driver, the
    same path Textual uses for clipboard and cursor-shape sequences.
    """

    def on_mount(self) -> None:
        if self._driver is not None:
            self._driver.write(PUSH_TITLE + SET_TITLE)

    def on_unmount(self) -> None:
        if self._driver is not None:
            self._driver.write(POP_TITLE)
