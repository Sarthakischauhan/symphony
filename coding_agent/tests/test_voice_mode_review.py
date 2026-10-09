"""Voice lifecycle regressions; all capture and speech providers are local fakes."""

from types import SimpleNamespace

import pytest

from coding_agent.credentials import OFFLINE_HINT
from coding_agent.tui.composer import voice_mode
from coding_agent.tui.composer.voice import GROK_VOICE_MODEL, UnavailableVoice


class FakeApp:
    def __init__(self):
        self._agent = object()
        self._busy = False
        self._voice_active = False
        self._voice_timer = None
        self._voice_addon = None
        self.workers = []
        self.callbacks = []
        self.notices = []
        self.turns = []
        self.focused = False
        self.widgets = {
            "#composer": SimpleNamespace(display=True, set_class=lambda *args: None,
                                         remove_class=lambda *args: None),
            "#prompt": SimpleNamespace(disabled=False, focus=self.focus),
        }

    def focus(self):
        self.focused = True

    def query_one(self, selector, widget_type):
        return self.widgets[selector]

    def set_interval(self, interval, callback):
        timer = SimpleNamespace(stopped=False)
        timer.stop = lambda: setattr(timer, "stopped", True)
        return timer

    def add_notice(self, text, severity=None):
        self.notices.append((text, severity))

    def run_worker(self, worker, **kwargs):
        self.workers.append(worker)

    def call_from_thread(self, callback, *args):
        self.callbacks.append(lambda: callback(*args))

    def _start_turn(self, turn):
        self.turns.append(turn.text)

    def _set_status(self, text):
        self.status = text


class Capture:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def listen(self):
        self.calls += 1
        if self.error:
            raise self.error
        return b"fake wav"


class Transcriber:
    def __init__(self, text):
        self.text = text
        self.models = []

    def transcribe(self, audio, *, model):
        assert audio == b"fake wav"
        self.models.append(model)
        return self.text


def assert_restored(app, timer):
    assert not app._voice_active
    assert app.widgets["#composer"].display
    assert not app.widgets["#prompt"].disabled
    assert app.focused
    assert timer.stopped
    assert app._voice_timer is None


@pytest.mark.parametrize("finish_before_cancel", [False, True])
@pytest.mark.parametrize("old_error", [None, UnavailableVoice("stale failure")])
def test_cancel_then_restart_ignores_old_worker_and_queued_result(finish_before_cancel, old_error):
    app = FakeApp()
    old = Capture(old_error)
    old_transcriber = Transcriber("old transcript")
    voice_mode.start_voice(app, capture=old, transcriber=old_transcriber)
    old_worker = app.workers[-1]
    if finish_before_cancel:
        old_worker()
    voice_mode.stop_voice(app, reason="escape")
    fresh = Capture()
    fresh_transcriber = Transcriber(" new transcript ")
    voice_mode.start_voice(app, capture=fresh, transcriber=fresh_transcriber)
    timer = app._voice_timer
    if not finish_before_cancel:
        old_worker()
    app.callbacks.pop(0)()
    assert app._voice_active
    assert app.widgets["#composer"].display
    assert app._voice_timer is timer
    assert not timer.stopped
    assert not app.turns
    assert not any(text == "stale failure" for text, _ in app.notices)
    assert fresh.calls == 0  # Even a delayed old worker uses its own dependencies.
    app.workers[-1]()
    app.callbacks.pop(0)()
    assert app.turns == ["new transcript"]
    assert fresh_transcriber.models == [GROK_VOICE_MODEL]
    assert app.widgets["#composer"].display  # Composer stays visible on submission.


@pytest.mark.parametrize("error,text,notice,severity", [
    (UnavailableVoice("no mic"), "unused", "no mic", "error"),
    (RuntimeError("capture failed"), "unused", "Voice mode failed · capture failed", "error"),
    (None, "  ", "Voice mode heard nothing.", "warning"),
])
def test_capture_error_or_empty_transcript_restores_ui(error, text, notice, severity):
    app = FakeApp()
    voice_mode.start_voice(app, capture=Capture(error), transcriber=Transcriber(text))
    timer = app._voice_timer
    app.workers[-1]()
    app.callbacks.pop(0)()
    assert_restored(app, timer)
    assert app.notices[-1] == (notice, severity)
    assert not app.turns


def test_agent_disappears_during_capture():
    app = FakeApp()
    voice_mode.start_voice(app, capture=Capture(), transcriber=Transcriber("hello"))
    timer = app._voice_timer
    app._agent = None
    app.workers[-1]()
    app.callbacks.pop(0)()
    assert_restored(app, timer)
    assert app.notices[-1] == (OFFLINE_HINT, "error")
    assert not app.turns


@pytest.mark.parametrize("startup", ["error", "raises", "register_raises", "arm_raises"])
def test_addon_startup_failure_restores_ui_and_closes(monkeypatch, startup):
    import coding_agent.addons.voice as addon_module

    instances = []

    class Addon:
        def __init__(self, **kwargs):
            self.closed = False
            instances.append(self)

        def open(self):
            if startup == "raises":
                raise RuntimeError("startup failed")
            return "startup failed" if startup == "error" else ""

        def arm(self):
            if startup == "arm_raises":
                raise RuntimeError("startup failed")

        def close(self):
            self.closed = True

    def register(addon):
        if startup == "register_raises":
            raise RuntimeError("startup failed")
        harness.addons.append(addon)

    monkeypatch.setattr(addon_module, "VoiceAddon", Addon)
    harness = SimpleNamespace(addons=[], register_addon=register)
    app = FakeApp()
    app._agent = SimpleNamespace(harness=harness)
    voice_mode.start_voice(app, capture=Capture(), transcriber=Transcriber("hello"))
    timer = app._voice_timer
    app.workers[-1]()
    app.callbacks.pop(0)()
    assert_restored(app, timer)
    assert instances[0].closed
    assert app._voice_addon is None
    assert "startup failed" in app.notices[-1][0]
    assert app.notices[-1][1] == "error"
    assert not app.turns


def test_existing_addon_is_armed_for_each_voice_turn(monkeypatch):
    import coding_agent.addons.voice as addon_module

    class Addon:
        arms = 0

        def open(self):
            return ""

        def arm(self):
            self.arms += 1

    monkeypatch.setattr(addon_module, "VoiceAddon", Addon)
    addon = Addon()
    app = FakeApp()
    app._agent = SimpleNamespace(harness=SimpleNamespace(addons=[addon]))
    assert voice_mode.ensure_voice_addon(app) == ""
    assert voice_mode.ensure_voice_addon(app) == ""
    assert addon.arms == 2
    assert app._voice_addon is addon


def test_worker_start_failure_restores_ui():
    app = FakeApp()

    def fail(*args, **kwargs):
        raise RuntimeError("worker failed")

    app.run_worker = fail
    voice_mode.start_voice(app, capture=Capture(), transcriber=Transcriber("hello"))
    assert app.widgets["#composer"].display
    assert app._voice_timer is None
    assert not app._voice_active
    assert app.notices[-1] == ("Voice mode failed · worker failed", "error")


def test_turn_handoff_failure_restores_ui():
    app = FakeApp()

    def fail(turn):
        raise RuntimeError("handoff failed")

    app._start_turn = fail
    voice_mode.start_voice(app, capture=Capture(), transcriber=Transcriber("hello"))
    timer = app._voice_timer
    app.workers[-1]()
    app.callbacks.pop(0)()
    assert_restored(app, timer)
    assert app.notices[-1] == ("Voice mode failed · handoff failed", "error")
