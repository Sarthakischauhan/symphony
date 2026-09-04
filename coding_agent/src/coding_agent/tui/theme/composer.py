"""Composer, menus, and footer CSS."""

from __future__ import annotations

COMPOSER_CSS = """
.notice {
    width: 100%;
    height: auto;
    min-height: 1;
    margin: 0 0 0 1;
    color: $muted;
}

/* Composer: a thin muted separator above a borderless prompt, with the
   all-caps mode label sitting on the prompt's first row at the right edge. */
#composer {
    width: 1fr;
    height: auto;
    min-height: 2;
    margin: 0 3;
    padding: 0 1;
    layout: vertical;
    background: $background;
    border: solid $panel-edge;
}

#composer:focus-within {
    border: solid $panel-edge-focus;
}

#composer-row {
    width: 100%;
    height: auto;
    layout: horizontal;
    background: $background;
}

#prompt {
    width: 1fr;
    max-width: 100%;
    height: auto;
    min-height: 1;
    max-height: 10;
    padding: 0;
    border: none;
    background: $background;
    color: $foreground;
    pointer: text;
}

#prompt:focus {
    border: none;
}

#prompt.-disabled {
    color: $muted-dim;
}

#prompt .text-area--placeholder {
    color: $muted;
}

#prompt .text-area--cursor-line {
    background: $background;
}

#composer-mode {
    width: auto;
    height: 1;
    padding: 0 0 0 3;
    color: $accent;
    background: $background;
}

#composer.plan-mode #composer-mode {
    color: $accent-plan;
}

#slash-menu {
    display: none;
    width: 1fr;
    height: auto;
    max-height: 10;
    margin: 0 3;
    padding: 1 1 0 1;
    background: $panel;
    border: round $panel-edge;
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}

#approval-menu {
    display: none;
}

#slash-menu > .option-list--option {
    padding: 0;
    background: $panel;
}

#slash-menu > .option-list--option-highlighted {
    background: $panel-light;
}

#slash-menu > .option-list--option-hover {
    background: $panel-light;
}

#slash-menu > .option-list--option-disabled {
    padding: 0;
    background: $panel;
}

#transcript ScrollBar {
    pointer: pointer;
}

/* Footer: workspace and context meter on the left, keyboard hint on the right. */
#status {
    width: 100%;
    height: 2;
    padding: 1 3 0 3;
    background: $background;
    color: $muted-dim;
}

#approval-menu.permission-menu {
    width: 100%;
    max-width: 100%;
    height: auto;
    max-height: 14;
    margin: 0 0 1 0;
    offset-x: 0;
    padding: 1 1 0 1;
    border: round $panel-edge;
    background: $background;
}

#approval-menu.permission-menu > .option-list--option {
    padding: 0 1;
    background: $background;
}

#approval-menu.permission-menu > .option-list--option-disabled {
    background: $background;
}

#approval-menu.permission-menu > .option-list--option-highlighted {
    background: $panel-light;
}

#approval-menu.permission-menu > .option-list--option-hover {
    background: $panel-light;
}

#slash-menu.file-menu {
    width: 1fr;
    max-height: 12;
    margin: 0 3 1 3;
    padding: 1 1 0 1;
    background: $panel;
    border: round $panel-edge;
}

#slash-menu.file-menu > .option-list--option,
#slash-menu.file-menu > .option-list--option-disabled {
    padding: 0 1;
    background: $panel;
}

#slash-menu.file-menu > .option-list--option-highlighted,
#slash-menu.file-menu > .option-list--option-hover {
    color: $foreground;
    background: $panel-light;
}
"""
