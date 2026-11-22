"""Styles of the ``/theme`` picker.

They join the app stylesheet rather than the screen's own CSS: a screen's CSS is
parsed without the palette variables (``$panel``, ``$accent``), and these must follow
whichever theme is being previewed.
"""

THEME_PICKER_CSS = """
ThemePickerScreen { align: center bottom; background: transparent; }
#theme-pane {
    width: 100%;
    height: auto;
    margin: 0 $space-page;
    padding: $space-inset;
    background: $panel;
    border: round $panel-edge;
}
#theme-title { height: auto; color: $muted; background: $panel; }
#theme-list {
    height: auto;
    max-height: 9;
    background: $panel;
    border: none;
    padding: 0;
    scrollbar-size-vertical: 1;
    scrollbar-color: $accent;
    scrollbar-background: $panel;
}
#theme-list > .option-list--option { padding: 0 $space-inset; background: $panel; }
#theme-list > .option-list--option-highlighted { background: $panel-light; text-style: bold; }
#theme-list > .option-list--option-hover { background: $panel-light; }
#theme-sample { height: auto; padding: 0 $space-inset; background: $panel; }
"""

__all__ = ["THEME_PICKER_CSS"]
