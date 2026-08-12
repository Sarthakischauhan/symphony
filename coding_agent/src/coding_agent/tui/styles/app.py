"""Textual CSS for the main Symphony application."""

from __future__ import annotations

APP_CSS = """
$background: #181818;
$panel: #202020;
$panel-light: #292929;
$line: #393939;
$muted: #727272;

Screen {
    layout: vertical;
    background: $background;
    color: #d4d4d4;
}

#topbar {
    height: 3;
    padding: 1 3 0 3;
    background: $background;
}

#transcript {
    width: 100%;
    height: 1fr;
    padding: 1 10 2 10;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: $background;
}

.welcome {
    width: 72;
    height: auto;
    min-height: 10;
    margin: 2 0 1 2;
    padding: 1 2;
    border-left: thick #777777;
    color: #bcbcbc;
}

.message {
    width: 100%;
    height: auto;
    margin: 1 0 0 0;
    padding: 1 2;
}

.user-message {
    background: $panel-light;
    border-left: solid #777777;
}

.assistant-message {
    padding-left: 1;
    background: $background;
}

.thinking-status {
    width: 100%;
    height: 2;
    padding: 0 0 0 3;
    color: $muted;
}

.run-process {
    width: 100%;
    height: auto;
    margin: 0;
    padding: 0 0 0 1;
    border-top: none;
    background: $background;
}

.run-process > CollapsibleTitle {
    width: auto;
    padding: 0 1;
    color: #666666;
    background: $background;
}

.run-process > CollapsibleTitle:hover {
    color: #a0a0a0;
    background: #202020;
}

.run-process > Contents {
    padding: 0 0 0 1;
}

.reasoning-summary {
    width: 100%;
    height: auto;
    margin: 0 0 1 0;
    padding: 0 2 0 3;
    color: #777777;
    border-left: solid #343434;
}

.tool-call {
    width: 100%;
    height: auto;
    min-height: 2;
    margin: 0 0 0 1;
    padding: 0 0 0 1;
    border-left: solid #383838;
    background: $background;
}

.tool-call > CollapsibleTitle {
    width: auto;
    padding: 0 1;
    color: #666666;
    background: $background;
}

.tool-call > CollapsibleTitle:hover {
    color: #a0a0a0;
    background: #202020;
}

.tool-call.status-preparing > CollapsibleTitle,
.tool-call.status-running > CollapsibleTitle {
    color: #d7a84b;
}

.tool-call.status-done > CollapsibleTitle {
    color: #72a57a;
}

.tool-call.status-failed > CollapsibleTitle {
    color: #d66b73;
}

.tool-call > Contents {
    padding: 0 0 0 1;
}

.diff-tool {
    margin-top: 1;
    margin-bottom: 1;
    padding-bottom: 1;
    background: #1b1b1b;
    border-left: solid #454545;
}

.notice {
    width: 100%;
    height: auto;
    min-height: 1;
    margin: 0 0 0 1;
    color: $muted;
}

#composer {
    width: 1fr;
    height: 6;
    margin: 0 10 1 10;
    padding: 0;
    background: $panel;
    border: solid #505050;
}

#slash-menu {
    display: none;
    width: 1fr;
    height: auto;
    max-height: 10;
    margin: 0 10;
    padding: 1 1 0 1;
    background: #202020;
    border: solid #3f3f3f;
    border-bottom: none;
}

#composer:focus-within {
    border: solid #888888;
}

#composer.plan-mode {
    border: solid #d8bd62;
}

#composer.plan-mode:focus-within {
    border: solid #ffe89a;
}

#prompt {
    width: 100%;
    height: 3;
    padding: 0 1;
    border: none;
    background: $panel;
    color: #eeeeee;
}

#prompt:focus {
    border: none;
}

#prompt.-disabled {
    color: #777777;
}

#composer-hint {
    height: 1;
    padding: 0 1;
    color: #595959;
    text-align: right;
    background: $panel;
}

#status {
    width: 100%;
    height: 1;
    padding: 0 3;
    background: #141414;
    color: #686868;
}
"""
