"""Voice lifecycle regressions; no audio hardware or provider access required."""
import asyncio
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from coding_agent.addons.voice import stream as module


def test_close_before_start_and_restart(monkeypatch):
    async def session(self):
        self._ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module.VoiceStream, "_session", session)
    voice = module.VoiceStream()
    voice.close()
    for _ in range(2):
        voice.start()
        assert voice._thread.is_alive()
        voice.close()
        assert voice._thread is None
        assert voice._closed.is_set()
        assert voice._loop is None
    voice.say("after close")


def test_close_cancels_connection_startup(monkeypatch):
    entered = threading.Event()

    async def connect(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=connect))
    monkeypatch.setattr(module, "grok_voice_credentials", lambda: ("fake", {}))
    voice = module.VoiceStream()
    starter = threading.Thread(target=voice.start)
    starter.start()
    assert entered.wait(2)
    voice.close()
    starter.join(2)
    assert not starter.is_alive()
    assert voice._thread is None


def test_close_from_worker_does_not_join_itself(monkeypatch):
    errors = []

    async def session(self):
        try:
            self.close()
        except Exception as exc:
            errors.append(exc)
        await asyncio.Event().wait()

    monkeypatch.setattr(module.VoiceStream, "_session", session)
    voice = module.VoiceStream()
    voice.start()
    assert voice._closed.wait(2)
    voice.close()
    assert not errors
    assert voice._thread is None
    assert voice._loop is None


@pytest.mark.parametrize("failure", ["initial_send", "mic", "disconnect"])
def test_session_always_cleans_up(monkeypatch, failure):
    cleaned = []

    class Socket:
        async def send(self, message):
            if failure == "initial_send":
                raise RuntimeError("send failed")

        async def close(self):
            cleaned.append("socket")

    async def connect(*args, **kwargs):
        return Socket()

    async def mic(socket):
        try:
            if failure == "mic":
                raise RuntimeError("mic failed")
            await asyncio.Event().wait()
        finally:
            cleaned.append("mic")

    async def events(socket):
        try:
            if failure != "disconnect":
                await asyncio.Event().wait()
        finally:
            cleaned.append("events")

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=connect))
    monkeypatch.setattr(module, "grok_voice_credentials", lambda: ("fake", {}))
    voice = module.VoiceStream()
    monkeypatch.setattr(voice, "_pump_mic", mic)
    monkeypatch.setattr(voice, "_pump_events", events)
    voice.start()
    assert voice._closed.wait(2)
    voice.close()
    assert "socket" in cleaned
    if failure != "initial_send":
        assert "mic" in cleaned and "events" in cleaned
    assert bool(voice.error) == (failure != "disconnect")


def test_response_done_keeps_session_open(monkeypatch):
    class Player:
        def __init__(self, **kwargs):
            pass

        def finish(self):
            pass

        def close(self):
            pass

    class Socket:
        def __aiter__(self):
            async def messages():
                yield json.dumps({"type": "response.audio.done"})
                yield json.dumps({"type": "response.done"})
            return messages()

    monkeypatch.setattr(module, "_PcmPlayer", Player)

    async def run():
        voice = module.VoiceStream()
        voice._stop = asyncio.Event()
        await voice._pump_events(Socket())
        assert not voice._stop.is_set()

    asyncio.run(run())


def test_mic_queue_overflow_is_handled_on_loop(monkeypatch):
    callbacks = []
    exited = []

    class Input:
        def __init__(self, **kwargs):
            callbacks.append(kwargs["callback"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            exited.append(True)

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(RawInputStream=Input))

    async def run():
        errors = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        voice = module.VoiceStream()
        voice._stop = asyncio.Event()

        async def send(message):
            await asyncio.Event().wait()

        task = asyncio.create_task(voice._pump_mic(SimpleNamespace(send=send)))
        await asyncio.sleep(0)
        for _ in range(100):
            callbacks[0](b"\0\0", 1, None, None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not errors
        assert exited == [True]

    asyncio.run(run())


class Process:
    def __init__(self):
        self.killed = False
        self.waits = 0

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waits += 1
        if timeout is not None:
            raise module.subprocess.TimeoutExpired("fake", timeout)


@pytest.mark.parametrize("command", [None, ["fake"]])
def test_playback_launch_failure_removes_wav(monkeypatch, tmp_path, command):
    path = tmp_path / "reply.wav"
    path.write_bytes(b"fake")
    monkeypatch.setattr(module, "_write_wav", lambda pcm: str(path))
    monkeypatch.setattr(module, "_wav_command", lambda path: command)

    def fail(*args, **kwargs):
        raise OSError("cannot launch")

    monkeypatch.setattr(module.subprocess, "Popen", fail)
    states = []
    player = module._PcmPlayer(on_speaking=states.append)
    player.write(b"\0\0")
    if command is None:
        player.finish()
    else:
        with pytest.raises(OSError):
            player.finish()
    assert not path.exists()
    assert True not in states


def test_playback_duplicate_done_replacement_and_close(monkeypatch, tmp_path):
    paths = []
    processes = []

    def wav(pcm):
        path = tmp_path / f"{len(paths)}.wav"
        path.write_bytes(pcm)
        paths.append(path)
        return str(path)

    def popen(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process

    monkeypatch.setattr(module, "_write_wav", wav)
    monkeypatch.setattr(module, "_wav_command", lambda path: ["fake", path])
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    states = []
    player = module._PcmPlayer(on_speaking=states.append)
    player.write(b"\0\0")
    player.finish()
    player.finish()
    assert states == [True]
    player.write(b"\0\0")
    player.finish()
    assert processes[0].killed and processes[0].waits
    assert not paths[0].exists()
    player.close()
    player.close()
    assert processes[1].killed and processes[1].waits
    assert not paths[1].exists()
    assert states[-1] is False


def test_playback_timeout_kills_reaps_and_removes_file(tmp_path):
    path = tmp_path / "reply.wav"
    path.write_bytes(b"fake")
    states = []
    player = module._PcmPlayer(on_speaking=states.append)
    process = Process()
    player._player = process
    player._path = str(path)
    player._wait(process, str(path))
    assert process.killed and process.waits == 2
    assert not path.exists()
    assert player._player is None
    assert states == [False]
