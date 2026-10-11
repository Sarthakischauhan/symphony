"""Voice opt-in must not leak into typed turns or subagents."""
import asyncio
from types import SimpleNamespace

from coding_agent.addons.voice import addon as module


class _Speaker:
    def __init__(self, stream):
        self._stream = stream

    def finish(self, text=""):
        if text:
            self._stream.said.append(text)

    def close(self, *, timeout=0.0):
        self._stream.closed = True


class FakeStream:
    error = ""
    _on_speaking = None

    def __init__(self):
        self.said = []
        self.closed = False

    def start(self):
        pass

    def hold(self):
        pass

    def say(self, text):
        self.said.append(text)

    def close(self, *, timeout=0.0):
        self.closed = True


def test_typed_turn_stays_silent_after_voice_turn(monkeypatch):
    stream = FakeStream()
    monkeypatch.setattr(module, "StreamingSpeaker", lambda **kwargs: _Speaker(stream))
    addon = module.VoiceAddon(stream=stream)
    addon.arm()
    addon._open = True
    addon.feed("Voice answer.")
    asyncio.run(addon.after_run(result=SimpleNamespace(
        output_text="Voice answer.\n\n## Spoken summary\nI updated the helper.",
        reply_aloud=True,
    )))
    addon.arm()
    addon._open = True
    addon.feed("Typed answer.")
    asyncio.run(addon.after_run(result=SimpleNamespace(output_text="Typed answer.", reply_aloud=False)))
    assert stream.said == ["I updated the helper."]
    # A typed turn does not speak and does not tear the socket down.
    assert not stream.closed
    addon.close()
    assert stream.closed


def test_rearming_speaks_each_summary_on_the_same_socket(monkeypatch):
    stream = FakeStream()
    monkeypatch.setattr(module, "StreamingSpeaker", lambda **kwargs: _Speaker(stream))
    addon = module.VoiceAddon(stream=stream)
    for text in ("First", "Second"):
        addon.arm()
        addon._open = True
        addon.feed(text)
        spoken = f"Done with {text.lower()}."
        asyncio.run(addon.after_run(result=SimpleNamespace(
            output_text=f"{text}\n\n## Spoken summary\n{spoken}",
            reply_aloud=True,
        )))
        assert stream.said[-1] == spoken
        assert not stream.closed
    addon.close()
    assert stream.closed
    assert addon.fork_for_child(None) is None
