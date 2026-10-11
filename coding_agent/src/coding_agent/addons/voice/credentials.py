"""xAI audio endpoint, TTS voice, and the bearer every voice socket uses.

The TUI's microphone path and the voice add-on both authenticate here, so this
lives with the add-on and the TUI imports it, never the other way round.
"""

from __future__ import annotations

import os

# Built-in TTS voice. eve is the API default.
GROK_TTS_VOICE = "eve"


class UnavailableVoice(RuntimeError):
    """Raised when the microphone or the Grok voice model cannot be reached."""


# The Grok CLI chat proxy only serves chat models. ``/chat/completions`` there
# is a 404, so voice audio goes to the xAI audio endpoint. The bearer is still
# the same device-login token a ``grok:`` model call uses.
XAI_AUDIO_BASE_URL = "https://api.x.ai/v1"


def grok_voice_credentials() -> tuple[str, dict[str, str]]:
    """Bearer and extra headers for one voice transcription.

    An ``XAI_API_KEY`` wins, same as model calls. Otherwise the stored xAI
    device login is reused. The chat-proxy base URL is not used: it has no
    audio route.
    """
    api_key = os.getenv("XAI_API_KEY", "").strip()
    if api_key:
        return api_key, {}
    from core_ai.oauth.runtime import oauth_runtime_for

    runtime = oauth_runtime_for("grok")
    if runtime is None or not runtime.api_key:
        raise UnavailableVoice(
            "Voice mode needs a Grok sign-in. Run /provider and choose xAI, or set XAI_API_KEY."
        )
    return runtime.api_key, dict(runtime.extra_headers)
