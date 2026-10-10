"""Start/stop lifecycle of the microphone paths, and lazy audio imports.

A fake PortAudio feeds blocks from its own thread, like a sound card. No
audio device, network, or provider is touched.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
import types

import pytest

from coding_agent.addons.voice import stream as stream_module
from coding_agent.tui.composer import voice as voice_module


class FakeInput:
    """Raw input stream that calls back every ``period`` until closed."""

    open_now = 0
    open_max = 0
    opened = 0
    lock = threading.Lock()

    def __init__(self, *, callback, blocksize=0, samplerate=16_000, level=0, **kwargs):
        self.callback = callback
        self.frames = blocksize or 512
        self.level = level
        self.period = 0.005
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self._run, name="fake-portaudio", daemon=True)

    def _run(self):
        sample = int(self.level).to_bytes(2, "little", signed=True)
        block = memoryview(bytearray(sample * self.frames))
        while not self.halt.wait(self.period):
            self.callback(block, self.frames, None, None)

    def __enter__(self):
        with FakeInput.lock:
            FakeInput.opened += 1
            FakeInput.open_now += 1
            FakeInput.open_max = max(FakeInput.open_max, FakeInput.open_now)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.halt.set()
        self.thread.join()
        with FakeInput.lock:
            FakeInput.open_now -= 1


@pytest.fixture
def fake_portaudio(monkeypatch):
    FakeInput.open_now = FakeInput.open_max = FakeInput.opened = 0
    module = types.SimpleNamespace(RawInputStream=FakeInput)
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


class Socket:
    def __init__(self):
        self.appends = 0
        self.first = threading.Event()
        self.closed = threading.Event()

    async def send(self, message):
        if "input_audio_buffer.append" in message:
            self.appends += 1
            self.first.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Event().wait()

    async def close(self):
        self.closed.set()


@pytest.fixture
def fake_socket(monkeypatch):
    sockets = []

    async def connect(*args, **kwargs):
        sockets.append(Socket())
        return sockets[-1]

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=connect))
    monkeypatch.setattr(stream_module, "grok_voice_credentials", lambda: ("fake", {}))
    return sockets


def _voice_threads():
    return [t for t in threading.enumerate() if t.name in {"grok-voice", "fake-portaudio"}]


def test_stream_start_stop_start_reuses_one_mic_and_leaks_nothing(fake_portaudio, fake_socket):
    voice = stream_module.VoiceStream()
    for run in range(3):
        voice.start()
        voice.start()  # A second start while running is a no-op.
        deadline = time.monotonic() + 2
        while len(fake_socket) <= run or not fake_socket[run].first.wait(0.05):
            assert time.monotonic() < deadline
        voice.close()
        voice.close()  # Safe double stop.
    voice.close(timeout=2)
    assert len(fake_socket) == 3
    assert all(socket.closed.is_set() for socket in fake_socket)
    assert FakeInput.opened == 3 and FakeInput.open_max == 1 and FakeInput.open_now == 0
    assert not _voice_threads()
    assert voice._thread is None and voice._loop is None
    assert not voice.error


def test_stream_close_does_not_wait_for_a_hanging_connect(monkeypatch, fake_portaudio):
    entered = threading.Event()

    async def connect(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=connect))
    monkeypatch.setattr(stream_module, "grok_voice_credentials", lambda: ("fake", {}))
    voice = stream_module.VoiceStream()
    voice.start()
    assert entered.wait(2)
    started = time.perf_counter()
    voice.close()
    assert time.perf_counter() - started < 0.1  # The UI thread is not held.
    voice.close(timeout=2)
    assert not _voice_threads()
    assert FakeInput.opened == 0


def test_stream_stop_while_starting_then_restart(fake_portaudio, fake_socket):
    voice = stream_module.VoiceStream()
    voice.start()
    voice.close()  # Before the thread has even created its loop.
    voice.start()
    deadline = time.monotonic() + 2
    while not fake_socket or not fake_socket[-1].first.wait(0.05):
        assert time.monotonic() < deadline
    voice.close(timeout=2)
    assert FakeInput.open_max == 1 and FakeInput.open_now == 0
    assert not _voice_threads()


def test_stream_held_mic_sends_nothing(fake_portaudio, fake_socket):
    voice = stream_module.VoiceStream()
    voice.hold()
    voice.start()
    deadline = time.monotonic() + 2
    while FakeInput.opened == 0:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    time.sleep(0.1)
    assert fake_socket[-1].appends == 0
    voice.resume()
    assert fake_socket[-1].first.wait(2)
    voice.close(timeout=2)


def test_capture_close_releases_the_mic_during_listen(fake_portaudio):
    capture = voice_module.MicrophoneCapture()
    result = []
    worker = threading.Thread(target=lambda: result.append(capture.listen()))
    worker.start()
    deadline = time.monotonic() + 2
    while FakeInput.open_now == 0:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    started = time.perf_counter()
    capture.close()
    capture.close()
    worker.join(2)
    assert not worker.is_alive()
    assert time.perf_counter() - started < 0.5  # Not the 8 s recording cap.
    assert result == [None]
    assert FakeInput.open_now == 0
    assert capture.listen() is None
    assert FakeInput.opened == 1


def test_capture_ends_on_silence_after_speech(monkeypatch):
    class Speech(FakeInput):
        """Loud for 0.1 s of frames, then quiet; delivered without pacing."""

        def _run(self):
            loud = memoryview(bytearray((4000).to_bytes(2, "little", signed=True) * self.frames))
            quiet = memoryview(bytearray(2 * self.frames))
            sent = 0
            while not self.halt.is_set() and sent < 16_000 * 5:
                self.callback(loud if sent < 1_600 else quiet, self.frames, None, None)
                sent += self.frames

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(RawInputStream=Speech))
    started = time.perf_counter()
    audio = voice_module.MicrophoneCapture().listen()
    assert time.perf_counter() - started < 2
    # 512-frame blocks at 16 kHz; the recording stops 0.7 s of frames after speech.
    frames = (len(audio) - 44) // 2
    assert 1_600 + 11_200 <= frames <= 1_600 + 11_200 + 2 * 512


def test_pure_python_rms_matches_audioop():
    pcm = b"".join(n.to_bytes(2, "little", signed=True) for n in (0, 1000, -1000, 32767, -32768))
    assert voice_module._pcm16_rms(pcm, 2) == 20733  # audioop.rms of the same samples
    assert voice_module._pcm16_rms(b"", 2) == 0


def test_missing_portaudio_is_a_voice_error(monkeypatch):
    class NoPortAudio:
        def find_spec(self, name, path=None, target=None):
            if name == "sounddevice":
                raise OSError("PortAudio library not found")
            return None

    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    monkeypatch.setattr(sys, "meta_path", [NoPortAudio(), *sys.meta_path])
    monkeypatch.setattr(voice_module, "_install_voice_extra", lambda: pytest.fail("pip cannot add PortAudio"))
    with pytest.raises(voice_module.UnavailableVoice, match="PortAudio"):
        voice_module.MicrophoneCapture().listen()


_AUDIO_MODULES = ("sounddevice", "websockets", "_cffi_backend", "numpy", "audioop")


def _python(code: str, *, block_audio: bool = False) -> str:
    prelude = ""
    if block_audio:
        prelude = "import sys\nfor name in %r:\n    sys.modules[name] = None\n" % (_AUDIO_MODULES,)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    done = subprocess.run(
        [sys.executable, "-c", prelude + code], env=env, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_importing_the_tui_loads_no_audio_library():
    loaded = _python(
        "import sys\nimport coding_agent.tui.app\n"
        "import coding_agent.tui.composer.voice_mode\nimport coding_agent.addons.voice\n"
        "print(','.join(m for m in %r if m in sys.modules))" % (_AUDIO_MODULES,)
    )
    assert loaded == ""


def test_tui_and_voice_work_without_audio_libraries():
    out = _python(
        "import coding_agent.tui.app\n"
        "from coding_agent.tui.composer.voice import MicrophoneCapture, UnavailableVoice\n"
        "import coding_agent.tui.composer.voice as v\n"
        "v._install_voice_extra = lambda: None\n"
        "try:\n    MicrophoneCapture().listen()\nexcept UnavailableVoice as exc:\n    print('mic:', exc)\n"
        "from coding_agent.addons.voice.stream import VoiceStream\n"
        "s = VoiceStream(); s.start(); s._closed.wait(2); s.close(); print('stream:', s.error)\n",
        block_audio=True,
    )
    assert "mic: Voice mode could not install the microphone package" in out
    assert "stream: Voice mode needs the websockets package." in out
