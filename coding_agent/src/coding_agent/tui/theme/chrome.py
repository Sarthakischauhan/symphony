"""App chrome CSS: screen, topbar, transcript, messages, reasoning."""

from __future__ import annotations

CHROME_CSS = """
$background: #0A0A0A;
$panel: #171717;
$panel-light: #262626;
$panel-edge: #262626;
$panel-edge-focus: #8ca0cc;
$muted: #737373;
$blue: #7186c7;

Screen {
    layout: vertical;
    background: $background;
    color: #EDEDED;
}

#topbar {
    layout: horizontal;
    height: 5;
    padding: 1 3 0 3;
    background: $background;
}

#topbar-product {
    width: auto;
    height: 2;
    color: #e6e6e6;
    text-style: bold;
    content-align: left middle;
    background: $background;
}

#topbar-workspace {
    width: 1fr;
    height: 2;
    padding: 0 0 0 4;
    content-align: left middle;
    background: $background;
}

#topbar-model {
    width: auto;
    height: 2;
    padding: 0 1;
    content-align: center middle;
    color: #a0a0a0;
    background: $background;
}

#transcript {
    width: 100%;
    height: 1fr;
    padding: 1 8 2 8;
    /* Keep scrollbars out of the way until the user interacts with them. */
    scrollbar-size: 1 1;
    scrollbar-size-vertical: 1;
    scrollbar-color: transparent;
    scrollbar-color-hover: #606060;
    scrollbar-color-active: #707070;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
}

.welcome {
    width: 72;
    height: auto;
    min-height: 10;
    margin: 3 0 1 2;
    padding: 1 2;
    border-left: thick #3f3f3f;
    color: #bcbcbc;
}

.message {
    width: 100%;
    height: auto;
    margin: 1 0 0 1;
    padding: 0 2;
}

.user-message {
    background: $background;
    border-left: solid #7197e8;
    padding: 1 2;
}

.assistant-message {
    padding-left: 2;
    background: $background;
}

.thinking-status {
    width: auto;
    max-width: 72;
    height: 1;
    padding: 0 1 0 2;
    color: $muted;
}

.run-process {
    width: 100%;
    height: auto;
    margin: 0;
    padding: 0 0 0 3;
    background: $background;
}

.process-complete {
    width: auto;
    height: 1;
    margin: 1 0 0 1;
    color: #5f6a62;
}

.reasoning-block {
    width: 100%;
    height: auto;
    margin: 0;
    padding: 0;
    color: #5b9bd5;
    background: $background;
    pointer: pointer;
}

.reasoning-block > CollapsibleTitle {
    width: auto;
    padding: 0 1;
    color: #5b9bd5;
    background: $background;
    pointer: pointer;
}

.reasoning-block.is-complete > CollapsibleTitle {
    color: #5b9bd5;
}

.reasoning-block > CollapsibleTitle:hover {
    color: #83b8e8;
    background: #202020;
}

.reasoning-block > Contents {
    padding: 0;
}

.reasoning-scroll {
    width: 100%;
    height: auto;
    max-height: 12;
    padding: 0;
    scrollbar-size: 1 1;
    scrollbar-color: transparent;
    scrollbar-color-hover: #606060;
    scrollbar-color-active: #707070;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
}

.reasoning-text {
    width: 100%;
    height: auto;
    color: #5b9bd5;
}
"""
