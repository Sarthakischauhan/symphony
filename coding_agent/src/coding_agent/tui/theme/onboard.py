"""Onboarding and in-session provider wizard CSS."""

from __future__ import annotations

from coding_agent.tui.theme.modal import MODAL_BASE_CSS
from coding_agent.tui.theme.resume import RESUME_CSS

ONBOARD_CSS = RESUME_CSS + """
OnboardApp {
    background: #0a0a0a;
    color: #d0d0d0;
}

#onboard-page {
    width: 100%;
    height: 100%;
    padding: 1 2 0 2;
    background: #0a0a0a;
}

ProviderWizard {
    width: 100%;
    height: 1fr;
}

#onboard-title {
    height: 1;
    color: #ededed;
    text-style: bold;
}

#onboard-subtitle {
    height: 2;
    padding-top: 1;
    color: #737373;
}

#provider-list {
    width: 100%;
    height: 1fr;
    margin-top: 1;
    background: #0a0a0a;
    border: none;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-background: #0a0a0a;
}

#provider-list:focus {
    border: none;
}

#provider-list > .option-list--option {
    height: 3;
    padding: 0 2;
    background: #0a0a0a;
}

#provider-list > .option-list--option-highlighted {
    background: #1c1b17;
    color: #e1c16e;
}

#provider-key {
    width: 100%;
    height: 3;
    margin-top: 2;
    background: #141414;
    color: #ededed;
    border: tall #2a2a2a;
    padding: 0 1;
}

#provider-key:focus {
    border: tall #e1c16e;
}

#onboard-error {
    height: 1;
    margin-top: 1;
    color: #db6767;
}

#onboard-hint {
    height: 1;
    color: #656565;
    text-align: right;
}
"""

PROVIDER_MODAL_CSS = MODAL_BASE_CSS + """
ProviderOnboardScreen {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#provider-pane {
    width: 72%;
    max-width: 88;
    height: 28;
    padding: 1 2 1 2;
}

#provider-pane #onboard-title {
    height: 1;
    color: #ededed;
    text-style: bold;
}

#provider-pane #onboard-subtitle {
    height: 2;
    padding-top: 1;
    color: #737373;
}

#provider-pane ProviderWizard {
    width: 100%;
    height: 1fr;
}

#provider-pane #provider-list {
    width: 100%;
    height: 1fr;
    margin-top: 1;
    background: #101010;
    border: none;
}

#provider-pane #provider-list:focus {
    border: none;
}

#provider-pane #provider-list > .option-list--option {
    height: 3;
    padding: 0 1;
    background: #101010;
}

#provider-pane #provider-list > .option-list--option-highlighted {
    background: #1c1b17;
    color: #e1c16e;
}

#provider-pane #provider-key {
    width: 100%;
    height: 3;
    margin-top: 1;
    background: #141414;
    color: #ededed;
    border: tall #2a2a2a;
}

#provider-pane #provider-key:focus {
    border: tall #e1c16e;
}

#provider-pane #onboard-error {
    height: 1;
    color: #db6767;
}

#provider-pane #onboard-hint {
    height: 1;
    color: #656565;
}
"""
