"""App chrome CSS: screen, topbar, transcript, messages, reasoning."""

from __future__ import annotations

CHROME_CSS = """
/* Mock palette: deep dark canvas, purple accent, muted gray chrome.
   Keep in sync with SYMPHONY_COLORS in theme/colors.py. */
$background: #0A0A0A;
$foreground: #EDEDED;
$accent: #A371F7;
$accent-plan: #D8BD62;
$muted: #737373;
$muted-dim: #737373;
$panel: #171717;
$panel-light: #262626;
$panel-edge: #262626;
$panel-edge-focus: #484F58;

Screen {
    layout: vertical;
    background: $background;
    color: $foreground;
}

#topbar {
    width: 100%;
    height: 2;
    padding: 1 3 0 3;
    color: $muted-dim;
    background: $background;
}

#transcript {
    width: 100%;
    height: 1fr;
    padding: 0 3 1 3;
    /* Keep scrollbars out of the way until the user interacts with them. */
    scrollbar-size: 1 1;
    scrollbar-size-vertical: 1;
    scrollbar-color: transparent;
    scrollbar-color-hover: $panel-edge;
    scrollbar-color-active: $panel-edge-focus;
    scrollbar-background: transparent;
    scrollbar-background-hover: transparent;
    scrollbar-background-active: transparent;
}

.welcome {
    width: 72;
    height: auto;
    min-height: 10;
    margin: 2 0 1 1;
    padding: 1 2;
    border-left: thick $panel-edge;
    color: $muted;
}

.message {
    width: 100%;
    height: auto;
    margin: 1 0 0 1;
    padding: 0 2;
}

/* The user prompt is rendered as an accent `>` glyph plus the prompt text
   (see UserMessage); the glyph replaces the old coloured left border. */
.user-message {
    background: $background;
    padding: 0;
}

.run-summary {
    margin: 2 0 0 1;
    background: $background;
    border-left: solid #9b7bc3;
    padding: 1 2;
    color: #c2b5cf;
}

.assistant-message {
    padding-left: 3;
    background: $background;
}

.thinking-status {
    width: auto;
    max-width: 72;
    height: 1;
    padding: 0 1 0 3;
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
    background: $panel;
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
