"""Voice mode: slash command, Ctrl+A, the purple sweep, and the turn hand-off."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands.catalog import SLASH_COMMANDS, command_matches
from coding_agent.tui.composer.input import Composer
from coding_agent.tui.composer.voice import (
    GROK_VOICE_MODEL,
    VOICE_DARK_PURPLE,
    VOICE_LIGHT_PURPLE,
    VoiceBar,
    voice_bar_markup,
)
from coding_agent.tui.composer.voice_mode import start_voice


class ScriptedCapture:
    """Hold the utterance until ``release`` so the test can see the hidden composer."""

    def __init__(self, audio: bytes = b"wav") -> None:
        self.audio = audio
        self.calls = 0
        self.started = __import__("threading").Event()
        self.gate = __import__("threading").Event()

    def listen(self) -> bytes:
        self.calls += 1
        self.started.set()
        self.gate.wait(timeout=2)
        return self.audio

    def release(self) -> None:
        self.gate.set()


class ScriptedTranscriber:
    def __init__(self, text: str = "rename the helper") -> None:
        self.text = text
        self.models: list[str] = []

    def transcribe(self, audio: bytes, *, model: str) -> str:
        del audio
        self.models.append(model)
        return self.text


def test_voice_uses_grok_oauth_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from coding_agent.tui.composer.voice import grok_voice_credentials

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "core_ai.oauth.runtime.oauth_runtime_for",
        lambda provider_id, client=None: __import__("types").SimpleNamespace(
            api_key="oauth-token",
            base_url="https://cli-chat-proxy.grok.com/v1",
            extra_headers={"X-XAI-Token-Auth": "xai-grok-cli"},
        ) if provider_id == "grok" else None,
    )
    token, headers = grok_voice_credentials()
    assert token == "oauth-token"
    assert headers["X-XAI-Token-Auth"] == "xai-grok-cli"


def test_voice_api_key_skips_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    from coding_agent.tui.composer.voice import grok_voice_credentials

    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    monkeypatch.delenv("XAI_BASE_URL", raising=False)

    def fail(provider_id: str, client: object = None) -> None:
        raise AssertionError("oauth should not be consulted when a key is set")

    monkeypatch.setattr("core_ai.oauth.runtime.oauth_runtime_for", fail)
    token, headers = grok_voice_credentials()
    assert token == "xai-key"
    assert headers == {}


def test_voice_addon_speaks_before_and_after_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from coding_agent.addons.voice.addon import VoiceAddon

    said: list[str] = []

    class Stream:
        def __init__(self) -> None:
            self.held = False

        def say(self, text: str) -> None:
            said.append(text)

        def hold(self) -> None:
            self.held = True

        def _on_speaking(self, speaking: bool) -> None:
            said.append(f"speaking:{speaking}")

        def start(self) -> None:
            return None

        @property
        def error(self) -> str:
            return ""

        def close(self) -> None:
            said.append("closed")

    stream = Stream()
    fed: list[str] = []

    class Speaker:
        def __init__(self, *, on_speaking: object = None) -> None:
            del on_speaking
            self._sent = ""
            self._pending = ""

        def feed(self, text: str, *, force: bool = False) -> None:
            from coding_agent.addons.voice.speak import _split_ready

            fresh = text[len(self._sent):] if text.startswith(self._sent) else text
            self._pending += fresh
            self._sent = text
            speakable, rest = _split_ready(self._pending)
            if force and not speakable and self._pending.strip():
                speakable, rest = self._pending.strip(), ""
            self._pending = rest
            if speakable:
                fed.append(speakable)

        def finish(self, text: str = "") -> None:
            fed.append(f"finish:{text}")

    addon = VoiceAddon(stream=stream)  # type: ignore[arg-type]
    from coding_agent.addons.voice import addon as addon_module

    monkeypatch.setattr(addon_module, "StreamingSpeaker", Speaker)
    addon.arm()
    assert addon.open() == ""
    addon.feed("Renamed it. The helper is updated")
    addon.feed("Renamed it. The helper is updated now.")

    async def _run() -> None:
        await addon.before_run(messages=[SimpleNamespace(role="user", content="rename the helper")])
        await addon.after_run(result=SimpleNamespace(output_text="Renamed it. The helper is updated now."))

    asyncio.run(_run())
    assert stream.held
    # No canned line. Speech is the model's own text, sent as it grows, and
    # the tail is flushed when the run ends.
    assert fed[0] == "Renamed it."
    assert fed[-1].startswith("finish:")


def test_spoken_text_strips_fences_and_limits_length() -> None:
    from coding_agent.tui.composer.voice import spoken_text

    assert spoken_text("```python\nprint(1)\n```\n\nDone.") == "Done."
    assert spoken_text("") == ""
    long = "word " * 200
    assert len(spoken_text(long)) <= 600
    assert spoken_text(long).endswith("…")


def test_voice_command_is_discoverable() -> None:
    assert "voice" in [command.name for command in SLASH_COMMANDS]
    assert [command.name for command in command_matches("/voi")] == ["voice"]


def test_voice_bar_runs_light_purple_to_dark_purple() -> None:
    assert voice_bar_markup(0) == ""
    first = voice_bar_markup(1)
    assert VOICE_LIGHT_PURPLE.removeprefix("#") in first
    full = voice_bar_markup(24)
    assert full.startswith(f"[#{VOICE_LIGHT_PURPLE.removeprefix('#')}]")
    assert full.endswith(f"[#{VOICE_DARK_PURPLE.removeprefix('#')}]#[/]")
    # A longer step only appends cells; it does not rebuild earlier colors.
    assert full.startswith(voice_bar_markup(4)[: len(voice_bar_markup(1))])


def test_ctrl_a_hides_composer_and_submits_transcript(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    started: list[str] = []
    app._agent = object()
    app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]
    capture = ScriptedCapture()
    transcriber = ScriptedTranscriber("add a voice bar")

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            start_voice(app, capture=capture, transcriber=transcriber)
            await pilot.pause()
            assert capture.started.wait(timeout=2)
            composer = app.query_one("#composer", Composer)
            bar = app.query_one("#voice-bar", VoiceBar)
            assert composer.display is False
            assert bar.display is True
            assert app._voice_active
            capture.release()
            for _ in range(20):
                await pilot.pause(0.05)
                if started:
                    break
            assert capture.calls == 1
            assert transcriber.models == [GROK_VOICE_MODEL]
            assert started == ["add a voice bar"]
            # The composer stays hidden until the spoken answer finishes.
            # Restoring it here is what made it flicker against the bar.
            assert composer.display is False
            assert bar.display is True
            assert not app._voice_active

    asyncio.run(_run())


def test_slash_voice_uses_the_same_toggle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    submitted: list[str] = []
    app._agent = object()
    app._start_turn = lambda turn: submitted.append(turn.text)  # type: ignore[method-assign]
    from coding_agent.tui.composer import voice_mode

    capture = ScriptedCapture()
    monkeypatch.setattr(voice_mode, "MicrophoneCapture", lambda: capture)
    monkeypatch.setattr(voice_mode, "GrokVoiceTranscriber", lambda: ScriptedTranscriber("fix the footer"))

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await app._run_slash_command("/voice")
            await pilot.pause()
            assert capture.started.wait(timeout=2)
            assert app.query_one("#composer", Composer).display is False
            capture.release()
            for _ in range(20):
                await pilot.pause(0.05)
                if submitted:
                    break
            assert submitted == ["fix the footer"]

    asyncio.run(_run())


def test_escape_leaves_voice_mode_without_a_turn(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    started: list[str] = []
    app._agent = object()
    app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]

    capture = ScriptedCapture(b"")

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            start_voice(app, capture=capture, transcriber=ScriptedTranscriber())
            await pilot.pause()
            assert capture.started.wait(timeout=2)
            assert app._voice_active
            await pilot.press("escape")
            await pilot.pause()
            assert not app._voice_active
            assert app.query_one("#composer", Composer).display is True
            capture.release()
            await pilot.pause(0.2)
            assert started == []

    asyncio.run(_run())


def test_voice_mode_refuses_while_busy(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    app._agent = object()
    app._busy = True

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await app._run_slash_command("/voice")
            await pilot.pause()
            assert not app._voice_active
            assert app.query_one("#composer", Composer).display is True

    asyncio.run(_run())
