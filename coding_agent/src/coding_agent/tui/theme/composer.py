"""Composer, menus, and status CSS."""

from __future__ import annotations

COMPOSER_CSS = """
.notice {
    width: 100%;
    height: auto;
    min-height: 1;
    margin: 0 0 0 1;
    color: $muted;
}

#composer {
    width: 1fr;
    height: auto;
    min-height: 6;
    margin: 0 8 1 8;
    padding: 0;
    layout: vertical;
    background: #101010;
    border: round $blue;
}

#slash-menu {
    display: none;
    width: 1fr;
    height: auto;
    max-height: 10;
    margin: 0 10;
    padding: 1 1 0 1;
    background: #202020;
    border: round $panel-edge;
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}

#approval-menu {
    display: none;
}

#slash-menu > .option-list--option {
    padding: 0;
    background: #202020;
}

#slash-menu > .option-list--option-highlighted {
    background: #383838;
}

#slash-menu > .option-list--option-hover {
    background: #383838;
}

#slash-menu > .option-list--option-disabled {
    padding: 0;
    background: #202020;
}

#composer:focus-within {
    border: round #91a7ed;
}

#composer.plan-mode {
    border: round #9d8950;
}

#composer.plan-mode:focus-within {
    border: round #d8bd62;
}

#prompt {
    width: 100%;
    height: auto;
    min-height: 3;
    max-height: 10;
    padding: 0 2;
    border: none;
    background: #101010;
    color: #eeeeee;
    pointer: text;
}

#composer-footer {
    width: 100%;
    height: 1;
    padding: 0 2;
    background: #101010;
}

#transcript ScrollBar {
    pointer: pointer;
}

#prompt:focus {
    border: none;
}

#prompt.-disabled {
    color: #777777;
}

#composer-hint {
    width: 1fr;
    height: 1;
    color: #595959;
    text-align: right;
    background: #101010;
}

#composer-mode {
    width: auto;
    height: 1;
    color: #596585;
    background: #101010;
}

#composer.plan-mode #composer-mode {
    color: #9d8950;
    background: #101010;
}

#status {
    width: 100%;
    height: 1;
    padding: 0 3;
    background: #111111;
    color: #686868;
}

#approval-menu.permission-menu {
    width: 100%;
    max-width: 100%;
    height: auto;
    max-height: 14;
    margin: 0;
    offset-x: 0;
    padding: 1 1 0 1;
    border: round #3d3d3d;
    background: #101010;
}

#approval-menu.permission-menu > .option-list--option {
    padding: 0 1;
    background: #101010;
}

#approval-menu.permission-menu > .option-list--option-disabled {
    background: #101010;
}

#approval-menu.permission-menu > .option-list--option-highlighted {
    background: #242a3c;
}

#approval-menu.permission-menu > .option-list--option-hover {
    background: #242a3c;
}

#slash-menu.file-menu {
    width: 1fr;
    max-height: 12;
    margin: 0 8 1 8;
    padding: 1 1 0 1;
    background: #101010;
    border: round #343434;
}

#slash-menu.file-menu > .option-list--option,
#slash-menu.file-menu > .option-list--option-disabled {
    padding: 0 1;
    background: #101010;
}

#slash-menu.file-menu > .option-list--option-highlighted,
#slash-menu.file-menu > .option-list--option-hover {
    color: #e4e4e4;
    background: #20283c;
}
"""
