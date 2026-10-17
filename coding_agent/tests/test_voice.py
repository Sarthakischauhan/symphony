"""Voice mode: entry, blinking composer border, and the turn hand-off."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands.catalog import SLASH_COMMANDS, command_matches
from coding_agent.tui.composer.input import Composer, PromptInput
from coding_agent.tui.composer.voice import (
    GROK_VOICE_MODEL,
    VOICE_DARK_PURPLE,
    VOICE_LIGHT_PURPLE,
)
from coding_agent.tui.composer.voice_mode import start_voice


class ScriptedCapture:
    """Hold each utterance until ``release`` so tests can inspect the indicator."""

    def __init__(self, audio: bytes = b"wav") -> None:
        self.audio = audio
        self.calls = 0
        self.started = __import__("threading").Event()
        self.gate = __import__("threading").Event()

    def listen(self) -> bytes:
        self.calls += 1
        self.started.set()
        self.gate.wait(timeout=2)
        self.gate.clear()
        return self.audio

    def release(self) -> None:
        self.gate.set()

    def close(self) -> None:
        self.closed = True


class ScriptedTranscriber:
    def __init__(self, text: str = "rename the helper") -> None:
        self.text = text
        self.lines: list[str] | None = None
        self.models: list[str] = []
        self.calls = 0

    def transcribe(self, audio: bytes, *, model: str) -> str:
        del audio
        self.models.append(model)
        self.calls += 1
        if self.lines is not None:
            index = self.calls - 1
            return self.lines[index] if index < len(self.lines) else "done"
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
    monkeypatch.setattr(
        "coding_agent.addons.voice.addon.StreamingSpeaker",
        lambda **kwargs: type("Speaker", (), {"finish": lambda self, text="": said.append(text), "close": lambda self, timeout=0.0: None})(),
    )

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

        def close(self, *, timeout: float = 0.0) -> None:
            said.append("closed")

    stream = Stream()
    addon = VoiceAddon(stream=stream)  # type: ignore[arg-type]
    addon.arm()
    assert addon.open() == ""
    # Streaming text is not dictated. Only the finished answer of a voice
    # question is, and only once the run completes.
    addon.feed("Renamed it. The helper is updated")
    addon.feed("Renamed it. The helper is updated now.")
    assert said == []

    async def _typed() -> None:
        await addon.before_run(messages=[SimpleNamespace(role="user", content="typed")])
        await addon.after_run(result=SimpleNamespace(output_text="Typed replies stay silent.", reply_aloud=False))

    asyncio.run(_typed())
    assert said == []

    addon.arm()
    addon._open = True

    async def _voice() -> None:
        await addon.before_run(messages=[SimpleNamespace(role="user", content="rename the helper")])
        await addon.after_run(
            result=SimpleNamespace(
                output_text=(
                    "Renamed it. The helper is updated now.\n\n"
                    "## Spoken summary\nI renamed the helper and updated its callers."
                ),
                reply_aloud=True,
            )
        )

    asyncio.run(_voice())
    # Spoken on the speech-to-speech socket. The written answer is not said.
    assert said == ["I renamed the helper and updated its callers."]


def test_spoken_text_strips_fences_and_limits_length() -> None:
    from coding_agent.addons.voice.summary import split_spoken_summary, spoken_summary, spoken_text

    answer = "Renamed the helper.\n\n## Spoken summary\nI renamed the helper and updated its callers."
    assert spoken_summary(answer) == "I renamed the helper and updated its callers."
    assert split_spoken_summary(answer) == (
        "Renamed the helper.",
        "I renamed the helper and updated its callers.",
    )
    assert split_spoken_summary("Renamed the helper.\n\n## Spoken") == ("Renamed the helper.", "")
    # No spoken section means silence. The whole answer is not dictated.
    assert spoken_summary("No marker here. The work is done.") == ""
    assert spoken_text("```python\nprint(1)\n```\n\nDone.") == "Done."
    assert spoken_text("") == ""
    long = "word " * 200
    assert len(spoken_text(long)) <= 600
    assert spoken_text(long).endswith("…")


def test_voice_command_is_discoverable() -> None:
    assert "voice" in [command.name for command in SLASH_COMMANDS]
    assert [command.name for command in command_matches("/voi")] == ["voice"]


def test_ctrl_a_keeps_composer_visible_and_submits_transcript(tmp_path: Path) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    started: list[str] = []
    app._agent = object()
    app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]
    capture = ScriptedCapture()
    transcriber = ScriptedTranscriber("add a voice bar")

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._agent = object()
            app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]
            start_voice(app, capture=capture, transcriber=transcriber)
            await pilot.pause()
            assert capture.started.wait(timeout=2)
            composer = app.query_one("#composer", Composer)
            assert composer.display is True
            assert composer.has_class("voice-light") or composer.has_class("voice-dark")
            assert app._voice_active
            capture.release()
            for _ in range(20):
                await pilot.pause(0.05)
                if transcriber.calls:
                    break
            # The first utterance is held in the composer. Ctrl+A starts the turn.
            assert started == []
            assert app._voice_active
            prompt = app.query_one("#prompt", PromptInput)
            assert "add a voice bar" in prompt.text
            await pilot.press("ctrl+a")
            for _ in range(20):
                await pilot.pause(0.05)
                if started:
                    break
            assert capture.calls >= 1
            assert transcriber.models == [GROK_VOICE_MODEL]
            assert started == ["add a voice bar"]
            # The composer stays visible throughout the voice turn.
            assert composer.display is True
            assert composer.has_class("voice-light") or composer.has_class("voice-dark")
            assert not app._voice_active

    asyncio.run(_run())


def test_slash_voice_uses_the_same_toggle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = CodingAgentApp(workspace=tmp_path)
    submitted: list[str] = []
    app._agent = object()
    app._start_turn = lambda turn: submitted.append(turn.text)  # type: ignore[method-assign]
    from coding_agent.tui.composer import voice as voice_module

    capture = ScriptedCapture()
    monkeypatch.setattr(voice_module, "MicrophoneCapture", lambda: capture)
    monkeypatch.setattr(voice_module, "GrokVoiceTranscriber", lambda: ScriptedTranscriber("fix the footer"))

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._agent = object()
            app._start_turn = lambda turn: submitted.append(turn.text)  # type: ignore[method-assign]
            await app._run_slash_command("/voice")
            await pilot.pause()
            assert capture.started.wait(timeout=2)
            assert app.query_one("#composer", Composer).display is True
            capture.release()
            for _ in range(20):
                await pilot.pause(0.05)
                if capture.calls >= 1 and not capture.gate.is_set():
                    break
            assert submitted == []
            await app._run_slash_command("/voice")
            for _ in range(20):
                await pilot.pause(0.05)
                if submitted:
                    break
            assert submitted == ["fix the footer"]

    asyncio.run(_run())


def test_live_transcript_shows_immediately_and_enter_submits(tmp_path: Path) -> None:
    """The realtime socket paints words as they arrive. Enter sends the turn."""
    from types import SimpleNamespace

    app = CodingAgentApp(workspace=tmp_path)
    started: list[str] = []
    harness = SimpleNamespace(addons=[], register_addon=lambda addon: harness.addons.append(addon))
    app._agent = SimpleNamespace(harness=harness)
    app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]

    class LiveStream:
        def __init__(self) -> None:
            self._on_transcript = None
            self._on_commit = None
            self._transcript = ""
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1
            if self._on_commit is not None:
                self._on_commit()

        def say(self, text: str) -> None:
            return None

        def start(self) -> None:
            return None

        def hold(self) -> None:
            return None

        def close(self, *, timeout: float = 0.0) -> None:
            return None

        @property
        def error(self) -> str:
            return ""

    stream = LiveStream()

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._agent = SimpleNamespace(harness=harness)
            app._start_turn = lambda turn: started.append(turn.text)  # type: ignore[method-assign]
            start_voice(app, stream=stream)
            await pilot.pause()
            assert app._voice_active
            app._voice_addon.stream._on_transcript("add a voice bar")
            for _ in range(20):
                await pilot.pause(0.05)
                if "voice bar" in app.query_one("#prompt", PromptInput).text:
                    break
            prompt = app.query_one("#prompt", PromptInput)
            assert "add a voice bar" in prompt.text
            assert started == []
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause(0.05)
                if started:
                    break
            assert stream.commits == 1
            assert started == ["add a voice bar"]
            assert not app._voice_active
            # A turn is in flight. Ctrl+A listens again instead of refusing,
            # and the next utterance waits behind the one already running.
            app._busy = True
            await pilot.press("ctrl+a")
            await pilot.pause()
            assert app._voice_active
            app._voice_addon.stream._on_transcript("now the footer")
            for _ in range(20):
                await pilot.pause(0.05)
                if "footer" in app.query_one("#prompt", PromptInput).text:
                    break
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause(0.05)
                if len(started) > 1 or getattr(app, "_queued_turns", None):
                    break
            queued = [turn.text for turn in getattr(app, "_queued_turns", [])]
            assert started == ["add a voice bar"]
            assert queued == ["now the footer"]

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


def test_voice_border_blinks_and_restores_theme(tmp_path: Path) -> None:
    from coding_agent.tui.composer.voice import VOICE_BLINK_INTERVAL_S
    from coding_agent.tui.composer.voice_mode import _set_voice_border, _advance_voice_border
    from textual.color import Color

    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer", Composer)
            original_border = composer.styles.border
            original_region = composer.region
            _set_voice_border(app, True)
            timer = app._voice_timer
            assert timer._interval == VOICE_BLINK_INTERVAL_S == 0.5
            await pilot.pause(0.05)
            assert composer.styles.border_top == ("round", Color.parse(VOICE_LIGHT_PURPLE))
            assert composer.display
            assert composer.region == original_region
            _advance_voice_border(app)
            await pilot.pause(0.05)
            assert composer.styles.border_top == ("round", Color.parse(VOICE_DARK_PURPLE))
            assert composer.region == original_region
            _set_voice_border(app, True)
            assert app._voice_timer is timer
            _set_voice_border(app, False)
            await pilot.pause(0.05)
            assert app._voice_timer is None
            assert not composer.has_class("voice-light")
            assert not composer.has_class("voice-dark")
            assert composer.styles.border == original_border
            assert not list(app.query("#voice-bar"))

    asyncio.run(_run())
