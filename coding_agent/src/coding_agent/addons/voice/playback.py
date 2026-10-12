"""Play MP3 bytes with whichever command-line player the machine has."""

from __future__ import annotations

import os

from coding_agent.addons.voice.credentials import UnavailableVoice


def play_mp3(audio: bytes) -> None:
    """Play MP3 bytes on the default output. No extra audio package required."""
    if not audio:
        return
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        handle.write(audio)
        path = handle.name
    try:
        player = _mp3_player(path)
        if player is None:
            raise UnavailableVoice("No audio player found to speak the reply.")
        subprocess.run(player, check=False, capture_output=True, timeout=120)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _mp3_player(path: str) -> list[str] | None:
    import shutil
    import sys

    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", path]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", path]
    return None
