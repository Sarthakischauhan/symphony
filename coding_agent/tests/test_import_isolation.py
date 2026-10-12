"""Headless layers must not load the Textual TUI.

The stdio server and the voice add-on run without a terminal UI (Zeron hosts
the server; the add-on is a harness hook). Each check runs in a fresh
interpreter, because this test process has usually imported the TUI already.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

HEADLESS_MODULES = (
    "coding_agent.protocols.stdio.server",
    "coding_agent.protocols.stdio.commands",
    "coding_agent.addons.voice.addon",
    "coding_agent.addons.voice.speak",
    "coding_agent.addons.voice.stream",
)


def _loaded_after_import(module: str) -> list[str]:
    script = (
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        "print(','.join(sorted(name for name in sys.modules\n"
        "    if name == 'textual' or name.startswith(('textual.', 'coding_agent.tui')))))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ),
        check=True,
    )
    return [name for name in done.stdout.strip().split(",") if name]


@pytest.mark.parametrize("module", HEADLESS_MODULES)
def test_headless_module_does_not_load_textual_or_the_tui(module: str) -> None:
    assert _loaded_after_import(module) == []


def test_stdio_server_and_voice_addon_together_leave_textual_unloaded() -> None:
    script = (
        "import sys\n"
        "import coding_agent.protocols.stdio.server, coding_agent.addons.voice.addon\n"
        "print('textual' in sys.modules)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=True
    )
    assert done.stdout.strip() == "False"


def test_old_import_paths_hand_back_the_moved_objects() -> None:
    from coding_agent.addons.voice import credentials
    from coding_agent.commands import catalog
    from coding_agent.tui.commands import catalog as old_catalog
    from coding_agent.tui.composer import voice as tui_voice

    assert old_catalog.SLASH_COMMANDS is catalog.SLASH_COMMANDS
    assert old_catalog.EFFORTS is catalog.EFFORTS
    assert old_catalog.command_matches is catalog.command_matches
    assert tui_voice.grok_voice_credentials is credentials.grok_voice_credentials
    assert tui_voice.UnavailableVoice is credentials.UnavailableVoice
