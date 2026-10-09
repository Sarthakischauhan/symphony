"""Voice opt-in must not leak into typed turns or subagents."""
import asyncio
from types import SimpleNamespace

from coding_agent.addons.voice import addon as module


class FakeStream:
    error = ""
    _on_speaking = None

    def start(self):
        pass

    def hold(self):
        pass

    def close(self):
        pass


class FakeSpeaker:
    instances = []

    def __init__(self, **kwargs):
        self.fed = []
        self.finished = []
        self.closed = False
        self.instances.append(self)

    def feed(self, text, **kwargs):
        self.fed.append((text, kwargs))

    def finish(self, text):
        self.finished.append(text)

    def close(self):
        self.closed = True


def test_typed_turn_stays_silent_after_voice_turn(monkeypatch):
    FakeSpeaker.instances = []
    monkeypatch.setattr(module, "StreamingSpeaker", FakeSpeaker)
    addon = module.VoiceAddon(stream=FakeStream())
    addon.arm()
    addon.feed("Voice answer.")
    asyncio.run(addon.after_run(result=SimpleNamespace(output_text="Voice answer.")))
    addon.feed("Typed answer.")
    asyncio.run(addon.after_run(result=SimpleNamespace(output_text="Typed answer.")))
    assert len(FakeSpeaker.instances) == 1
    assert FakeSpeaker.instances[0].finished == ["Voice answer."]
    assert not FakeSpeaker.instances[0].closed
    addon.close()
    assert FakeSpeaker.instances[0].closed


def test_rearming_resets_first_clause_and_cancellation_closes_speaker(monkeypatch):
    FakeSpeaker.instances = []
    monkeypatch.setattr(module, "StreamingSpeaker", FakeSpeaker)
    addon = module.VoiceAddon(stream=FakeStream())
    for text in ("First", "Second"):
        addon.arm()
        addon.feed(text)
        speaker = FakeSpeaker.instances[-1]
        assert speaker.fed == [(text, {"force": True})]
        addon.close()
        assert speaker.closed
    assert addon.fork_for_child(None) is None
