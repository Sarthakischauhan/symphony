"""CPU, memory, and disk snapshots for a live agent process.

The helpers stay in the standard library so the dashboard works on macOS,
Linux, and Windows without an extra dependency. Each OS reads the numbers it
publishes and leaves the rest unknown rather than guessing.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentUsage:
    """One sample of a process. ``None`` means the OS did not report it."""

    pid: int
    alive: bool
    cpu_percent: float | None = None
    rss_bytes: int | None = None
    disk_bytes: int | None = None

    def line(self) -> str:
        """Single-row summary: ``cpu 12%  ram 48.0 MB  disk 1.2 KB``."""
        return (
            f"cpu {_percent(self.cpu_percent):>4}  "
            f"ram {_bytes(self.rss_bytes):>8}  "
            f"disk {_bytes(self.disk_bytes):>8}"
        )


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}%"


def _bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def process_alive(pid: int) -> bool:
    """True when ``pid`` is still a process. ``pid`` 0 and 1 are never ours."""
    if pid <= 1:
        return False
    if sys.platform == "win32":
        return _windows_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_alive(pid: int) -> bool:
    import ctypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return False
    ctypes.windll.kernel32.CloseHandle(process)
    return True


def sample_usage(
    pid: int,
    *,
    workspace: str | Path | None = None,
    previous_cpu_seconds: float | None = None,
    previous_at: float | None = None,
) -> tuple[AgentUsage, float | None, float]:
    """Sample one process and return ``(usage, cpu_seconds, sampled_at)``.

    CPU percent needs two samples. The first call returns ``cpu_percent=None``
    and a ``cpu_seconds`` value the caller should pass back next time.
    """
    sampled_at = time.monotonic()
    if not process_alive(pid):
        return AgentUsage(pid=pid, alive=False), None, sampled_at
    cpu_seconds, rss = _process_counters(pid)
    cpu_percent = _cpu_percent(cpu_seconds, previous_cpu_seconds, sampled_at, previous_at)
    disk = directory_size(workspace) if workspace else None
    return (
        AgentUsage(pid=pid, alive=True, cpu_percent=cpu_percent, rss_bytes=rss, disk_bytes=disk),
        cpu_seconds,
        sampled_at,
    )


def _cpu_percent(
    cpu_seconds: float | None,
    previous_cpu_seconds: float | None,
    sampled_at: float,
    previous_at: float | None,
) -> float | None:
    if (
        cpu_seconds is None
        or previous_cpu_seconds is None
        or previous_at is None
        or sampled_at <= previous_at
    ):
        return None
    elapsed = sampled_at - previous_at
    cores = os.cpu_count() or 1
    used = max(0.0, cpu_seconds - previous_cpu_seconds)
    return min(100.0 * cores, (used / elapsed) * 100.0)


def directory_size(path: str | Path | None) -> int | None:
    """Bytes used by ``path``. A file uses its size; a directory is walked."""
    if path is None:
        return None
    target = Path(path)
    try:
        if target.is_file():
            return target.stat().st_size
        if not target.is_dir():
            return None
        total = 0
        for root, _dirs, files in os.walk(target):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return None


def disk_free(path: str | Path | None = None) -> int | None:
    """Free bytes on the volume that holds ``path`` (or the cwd)."""
    try:
        return shutil.disk_usage(path or ".").free
    except OSError:
        return None


def _process_counters(pid: int) -> tuple[float | None, int | None]:
    if sys.platform == "linux":
        return _linux_counters(pid)
    if sys.platform == "darwin":
        return _darwin_counters(pid)
    if sys.platform == "win32":
        return _windows_counters(pid)
    return None, None


def _linux_counters(pid: int) -> tuple[float | None, int | None]:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None, None
    # comm can contain spaces and parentheses; fields after the last ")".
    tail = text.rsplit(")", 1)[-1].split()
    cpu_seconds = None
    if len(tail) >= 13:
        # utime and stime are fields 14 and 15 of stat, indexes 11 and 12 here.
        ticks = os.sysconf("SC_CLK_TCK") or 100
        cpu_seconds = (int(tail[11]) + int(tail[12])) / ticks
    rss = None
    if len(tail) >= 22:
        rss = int(tail[21]) * (os.sysconf("SC_PAGE_SIZE") or 4096)
    return cpu_seconds, rss


def _darwin_counters(pid: int) -> tuple[float | None, int | None]:
    import subprocess

    try:
        completed = subprocess.run(
            ["ps", "-o", "time=,rss=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    parts = completed.stdout.split()
    if len(parts) < 2:
        return None, None
    return _parse_ps_time(parts[0]), int(parts[1]) * 1024


def _parse_ps_time(value: str) -> float | None:
    """Parse ``ps`` TIME, which is ``[[dd-]hh:]mm:ss``."""
    days = 0
    clock = value
    if "-" in value:
        day_text, clock = value.split("-", 1)
        try:
            days = int(day_text)
        except ValueError:
            return None
    pieces = clock.split(":")
    try:
        numbers = [int(piece) for piece in pieces]
    except ValueError:
        return None
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    elif len(numbers) == 3:
        hours, minutes, seconds = numbers
    else:
        return None
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _windows_counters(pid: int) -> tuple[float | None, int | None]:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel = ctypes.windll.kernel32
    process = kernel.OpenProcess(0x1000 | 0x0400, False, pid)
    if not process:
        return None, None
    rss = None
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.windll.psapi
    if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        rss = int(counters.WorkingSetSize)
    cpu_seconds = None
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    if kernel.GetProcessTimes(
        process,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        cpu_seconds = (_filetime(kernel_time) + _filetime(user_time)) / 10_000_000
    kernel.CloseHandle(process)
    return cpu_seconds, rss


def _filetime(value: object) -> int:
    return (int(value.dwHighDateTime) << 32) + int(value.dwLowDateTime)  # type: ignore[attr-defined]
