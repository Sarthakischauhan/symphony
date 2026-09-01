"""Resume-screen CSS tokens."""

from __future__ import annotations

RESUME_CSS = """
ResumeApp {
    background: #0a0a0a;
    color: #d0d0d0;
}

#resume-page {
    width: 100%;
    height: 100%;
    padding: 1 2 0 2;
    background: #0a0a0a;
}

#resume-title {
    height: 1;
    color: #ededed;
    text-style: bold;
}

#resume-subtitle {
    height: 2;
    padding-top: 1;
    color: #737373;
}

#resume-list {
    width: 100%;
    height: 1fr;
    margin-top: 1;
    background: #0a0a0a;
    border: none;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-background: #0a0a0a;
}

#resume-list:focus {
    border: none;
}

#resume-list > .option-list--option {
    height: 3;
    padding: 0 2;
    background: #0a0a0a;
}

#resume-list > .option-list--option-highlighted {
    background: #1c1b17;
    color: #e1c16e;
}

#resume-hint {
    height: 1;
    color: #656565;
    text-align: right;
}
"""
