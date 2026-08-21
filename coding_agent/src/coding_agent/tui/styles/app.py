"""Textual CSS for the main Symphony application."""

from __future__ import annotations

APP_CSS = """
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
    height: 3;
    min-width: 20;
    padding: 0 1;
    content-align: center middle;
    border: round #3b3b3b;
    background: #0d0d0d;
}

#transcript {
    width: 100%;
    height: 1fr;
    padding: 1 8 2 8;
    scrollbar-size: 1 1;
    scrollbar-size-vertical: 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: $background;
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
    margin: 0 0 0 2;
    padding: 0 0 0 2;
    color: #777777;
    border-left: solid #383838;
    background: $background;
    pointer: pointer;
}

.reasoning-block > CollapsibleTitle {
    width: auto;
    padding: 0 1;
    color: #d7a84b;
    background: $background;
    pointer: pointer;
}

.reasoning-block.is-complete > CollapsibleTitle {
    color: #777777;
}

.reasoning-block > CollapsibleTitle:hover {
    color: #a0a0a0;
    background: #202020;
}

.reasoning-block > Contents {
    padding: 0 0 0 1;
}

.reasoning-scroll {
    width: 100%;
    height: auto;
    max-height: 12;
    padding: 0 2;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-background: $background;
}

.reasoning-text {
    width: 100%;
    height: auto;
    color: #858585;
}

.tool-call {
    width: 100%;
    height: auto;
    min-height: 1;
    margin: 0;
    padding: 0;
    background: $background;
    pointer: pointer;
}

.tool-call > CollapsibleTitle {
    width: 1;
    height: 0;
    padding: 0;
    color: transparent;
    background: transparent;
}

.bash-tool > CollapsibleTitle {
    display: none;
}

.tool-call-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: $background;
    pointer: pointer;
}

.tool-call-header:hover,
.tool-call-header:focus {
    background: #202020;
}

.tool-call-label {
    width: auto;
    height: 1;
    margin-right: 2;
    color: #666666;
    background: transparent;
}

.tool-call-command {
    width: 1fr;
    height: 1;
    color: #c8c8c8;
    background: transparent;
    overflow: hidden;
    text-overflow: ellipsis;
}

.tool-call-status {
    width: auto;
    height: 1;
    padding-left: 2;
    color: #666666;
    text-align: right;
    background: transparent;
}

.tool-call.status-preparing .tool-call-label,
.tool-call.status-preparing .tool-call-status,
.tool-call.status-running .tool-call-label,
.tool-call.status-running .tool-call-status {
    color: #d7a84b;
}

.tool-call.status-done .tool-call-label,
.tool-call.status-done .tool-call-status {
    color: #72a57a;
}

.tool-call.status-failed .tool-call-label,
.tool-call.status-failed .tool-call-status {
    color: #d66b73;
}

.tool-call > Contents {
    padding: 0;
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

.bash-tool {
    padding-right: 1;
}

.bash-tool-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: $background;
    pointer: pointer;
}

.bash-tool-header:hover,
.bash-tool-header:focus {
    background: #202020;
}

.bash-tool-label {
    width: auto;
    height: 1;
    margin-right: 2;
    color: #666666;
    background: transparent;
}

.bash-tool-command {
    width: 1fr;
    height: 1;
    color: #c8c8c8;
    background: transparent;
    overflow: hidden;
    text-overflow: ellipsis;
}

.bash-tool-status {
    width: auto;
    height: 1;
    padding-left: 2;
    color: #666666;
    text-align: right;
    background: transparent;
}

.bash-tool.status-preparing .bash-tool-label,
.bash-tool.status-preparing .bash-tool-status,
.bash-tool.status-running .bash-tool-label,
.bash-tool.status-running .bash-tool-status {
    color: #d7a84b;
}

.bash-tool.status-done .bash-tool-label,
.bash-tool.status-done .bash-tool-status {
    color: #72a57a;
}

.bash-tool.status-failed .bash-tool-label,
.bash-tool.status-failed .bash-tool-status {
    color: #d66b73;
}

.bash-tool-body {
    width: 100%;
    height: auto;
    padding: 0 1 0 3;
    color: #777777;
    background: $background;
}

.diff-tool {
    margin-top: 1;
    margin-bottom: 1;
    padding-bottom: 1;
    background: $background;
    border-left: solid #454545;
}

/* Keep collapsed Update cards visually consistent with the timeline while
   retaining strong line-level colors when the diff is expanded. */
.diff-tool > Contents,
.diff-tool .tool-call-header {
    background: $background;
}

.diff-tool .tool-call-header:hover,
.diff-tool .tool-call-header:focus {
    background: #202020;
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
    height: 3;
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

#slash-menu.permission-menu {
    width: 76%;
    max-width: 84;
    height: auto;
    max-height: 14;
    margin: 0 0 1 0;
    offset-x: 12%;
    padding: 1 1 0 1;
    border: round #3d3d3d;
    background: #101010;
}

#slash-menu.permission-menu > .option-list--option {
    padding: 0 1;
    background: #101010;
}

#slash-menu.permission-menu > .option-list--option-disabled {
    background: #101010;
}

#slash-menu.permission-menu > .option-list--option-highlighted {
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
