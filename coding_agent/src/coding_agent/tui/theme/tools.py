"""Tool-call widget CSS."""

from __future__ import annotations

TOOLS_CSS = """
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
    width: 13;
    height: 1;
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
    width: 10;
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
    padding: 0;
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
    width: 13;
    height: 1;
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
    width: 10;
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

.bash-tool.-collapsed .bash-tool-body {
    display: none;
}

.diff-tool {
    margin-top: 1;
    margin-bottom: 1;
    padding-bottom: 1;
    background: $background;
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

.tool-call-summary {
    width: 100%;
    height: 1;
    padding: 0 1 0 2;
    color: #666666;
    background: $background;
}
"""
