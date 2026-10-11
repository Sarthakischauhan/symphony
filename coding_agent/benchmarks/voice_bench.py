"""Voice capture and realtime-stream benchmark with a fake real-time microphone.

Not a test; pytest does not collect it and CI never runs it. No audio device
or provider is needed: ``sounddevice`` is replaced by ``FakeSoundDevice``,
whose input stream calls the callback from its own thread with one block of
16-bit silence every ``blocksize / samplerate`` seconds, paced against the
monotonic clock like a sound card. ``blocksize=0`` (the PortAudio default)
is treated as 512 frames. ``websockets`` is replaced by a socket that accepts
every send and never replies.

    python coding_agent/benchmarks/voice_bench.py               # this checkout
    python coding_agent/benchmarks/voice_bench.py --root /tmp/base --runs 5

``--root`` is a repository root; its ``*/src`` directories go first on
``sys.path``. Every run is a fresh interpreter. Reported values are medians.

  capture   ``MicrophoneCapture.listen()`` on a worker thread, as the TUI runs
            it, over silence: first frame delivered to the recorder, CPU while
            it listens, RSS growth, OS threads, then how long the microphone
            stays open after voice mode is stopped (``close()`` when the
            checkout has one; otherwise the stream stays open until the
            recording cap).
  stream    ``VoiceStream.start()`` with the mic listening: first PCM block
            sent on the socket, CPU while listening, RSS growth, OS threads,
            how long ``close()`` blocks its caller, and threads left 2 s later.
  import    ``import coding_agent.tui.app`` alone; with ``sounddevice``,
            ``websockets`` and ``audioop`` made unimportable
            (``import-missing``); and followed by importing ``sounddevice``
            and ``websockets`` (``import-audio``).
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

IDLE_SECONDS = 5.0
REPO = Path(__file__).resolve().parents[2]


def _rss_kb() -> int:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def _threads() -> int:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("Threads:"):
                return int(line.split()[1])
    return 0


def _cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


class FakeInputStream:
    """PortAudio-like raw input: one paced callback thread, one reused buffer."""

    first_frame_at: float | None = None

    def __init__(self, *, samplerate, channels, dtype, callback, blocksize=0, **kwargs):
        del dtype, kwargs
        self._rate = int(samplerate)
        self._frames = int(blocksize) or 512
        self._buffer = bytearray(self._frames * 2 * int(channels))
        self._callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.closed_at: float | None = None

    def _run(self) -> None:
        period = self._frames / self._rate
        deadline = time.monotonic() + period
        view = memoryview(self._buffer)
        while not self._stop.wait(max(0.0, deadline - time.monotonic())):
            if FakeInputStream.first_frame_at is None:
                FakeInputStream.first_frame_at = time.perf_counter()
            self._callback(view, self._frames, None, None)
            deadline += period

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="fake-portaudio", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()
        self._thread = None

    def close(self) -> None:
        self.stop()
        if self.closed_at is None:
            self.closed_at = time.perf_counter()
        FakeSoundDevice.last_closed_at = self.closed_at

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()


class FakeSoundDevice(types.ModuleType):
    last_closed_at: float | None = None

    def __init__(self) -> None:
        super().__init__("sounddevice")
        self.RawInputStream = FakeInputStream


class FakeSocket:
    def __init__(self) -> None:
        self.first_audio_at: float | None = None
        self.appends = 0
        self._never = None

    async def send(self, message: str) -> None:
        if '"input_audio_buffer.append"' in message:
            self.appends += 1
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter()

    def __aiter__(self):
        return self

    async def __anext__(self):
        import asyncio

        if self._never is None:
            self._never = asyncio.Event()
        await self._never.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        return None


def _bench_capture() -> dict[str, float]:
    sys.modules["sounddevice"] = FakeSoundDevice()
    from coding_agent.tui.composer.voice import MicrophoneCapture

    capture = MicrophoneCapture()
    threads_before = _threads()
    rss_before = _rss_kb()
    result: dict[str, object] = {}

    def listen() -> None:
        result["audio"] = capture.listen()
        result["returned_at"] = time.perf_counter()

    started = time.perf_counter()
    worker = threading.Thread(target=listen, name="textual-worker")
    worker.start()
    while FakeInputStream.first_frame_at is None:
        time.sleep(0.001)  # The bench samples; the code under test does not.
    first = FakeInputStream.first_frame_at - started
    cpu0, wall0 = _cpu(), time.perf_counter()
    time.sleep(IDLE_SECONDS)
    cpu = (_cpu() - cpu0) / (time.perf_counter() - wall0) * 100
    threads = _threads()
    rss = _rss_kb() - rss_before
    stop_at = time.perf_counter()
    if hasattr(capture, "close"):  # this checkout; the base has no way to stop listen()
        capture.close()
    worker.join(30)
    mic_open = (FakeSoundDevice.last_closed_at or time.perf_counter()) - stop_at
    return {
        "first_frame_ms": first * 1000,
        "idle_cpu_pct": cpu,
        "rss_delta_kb": rss,
        "threads_listening": threads,
        "threads_before": threads_before,
        "mic_open_after_stop_ms": mic_open * 1000,
    }


def _bench_stream() -> dict[str, float]:
    import asyncio

    sys.modules["sounddevice"] = FakeSoundDevice()
    socket = FakeSocket()

    async def connect(*args, **kwargs):
        return socket

    sys.modules["websockets"] = types.SimpleNamespace(connect=connect)  # type: ignore[assignment]
    os.environ["XAI_API_KEY"] = "bench"
    from coding_agent.addons.voice.stream import VoiceStream

    asyncio.new_event_loop().close()  # Load the event-loop machinery outside the window.
    stream = VoiceStream()
    threads_before = _threads()
    rss_before = _rss_kb()
    started = time.perf_counter()
    stream.start()
    while socket.first_audio_at is None:
        time.sleep(0.001)
    first = socket.first_audio_at - started
    cpu0, wall0 = _cpu(), time.perf_counter()
    time.sleep(IDLE_SECONDS)
    cpu = (_cpu() - cpu0) / (time.perf_counter() - wall0) * 100
    threads = _threads()
    rss = _rss_kb() - rss_before
    stream.hold()  # A coding run is in flight: mic open, nothing sent.
    time.sleep(0.2)
    cpu0, wall0 = _cpu(), time.perf_counter()
    time.sleep(IDLE_SECONDS)
    held_cpu = (_cpu() - cpu0) / (time.perf_counter() - wall0) * 100
    close0 = time.perf_counter()
    stream.close()
    close_ms = (time.perf_counter() - close0) * 1000
    time.sleep(2)
    return {
        "first_frame_ms": first * 1000,
        "idle_cpu_pct": cpu,
        "held_cpu_pct": held_cpu,
        "rss_delta_kb": rss,
        "threads_listening": threads,
        "threads_before": threads_before,
        "close_blocks_ms": close_ms,
        "threads_after_close": _threads(),
        "error": stream.error,
    }


def _bench_import(mode: str) -> dict[str, float]:
    if mode == "import-missing":
        for name in ("sounddevice", "websockets", "audioop"):
            sys.modules[name] = None  # type: ignore[assignment]
    started = time.perf_counter()
    import coding_agent.tui.app  # noqa: F401

    tui = time.perf_counter()
    audio = ("sounddevice", "websockets", "_cffi_backend", "numpy", "audioop")
    loaded = sorted(m for m in audio if sys.modules.get(m) is not None)
    if mode == "import-audio":
        import sounddevice  # noqa: F401
        import websockets  # noqa: F401
    return {
        "import_ms": (time.perf_counter() - started) * 1000,
        "tui_ms": (tui - started) * 1000,
        "audio_loaded_by_tui": ",".join(loaded) or "none",
    }


def _child(scenario: str) -> None:
    if scenario == "capture":
        out = _bench_capture()
    elif scenario == "stream":
        out = _bench_stream()
    else:
        out = _bench_import(scenario)
    print("BENCH " + json.dumps(out))


def _run(root: Path, scenario: str) -> dict[str, object]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in sorted(root.glob("*/src")))
    proc = subprocess.run(
        [sys.executable, __file__, "--child", scenario],
        env=env, capture_output=True, text=True, timeout=120, check=True,
    )
    line = next(line for line in proc.stdout.splitlines() if line.startswith("BENCH "))
    return json.loads(line[6:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--child")
    args = parser.parse_args()
    if args.child:
        _child(args.child)
        return
    # Same footing for every checkout: bytecode compiled before timing imports.
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", *map(str, sorted(args.root.glob("*/src")))],
        check=True,
    )
    for scenario in ("import", "import-missing", "import-audio", "capture", "stream"):
        runs = [_run(args.root, scenario) for _ in range(args.runs)]
        summary = {}
        for key, value in runs[0].items():
            if isinstance(value, (int, float)):
                summary[key] = round(statistics.median(float(r[key]) for r in runs), 2)
            else:
                summary[key] = sorted({str(r[key]) for r in runs})
        print(json.dumps({"scenario": scenario, "root": str(args.root), "runs": args.runs, **summary}))


if __name__ == "__main__":
    main()
