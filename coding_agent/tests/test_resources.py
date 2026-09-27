"""Resource helpers format samples and read each OS without guessing."""

from __future__ import annotations

from coding_agent.resources.usage import (
    AgentUsage,
    _cpu_percent,
    _parse_ps_time,
    directory_size,
    process_alive,
    sample_usage,
)


def test_usage_line_formats_known_and_unknown() -> None:
    usage = AgentUsage(pid=1, alive=True, cpu_percent=12.4, rss_bytes=48 * 1024 * 1024, disk_bytes=1200)
    assert usage.line() == "cpu    12%   ram  48.0 MB   disk   1.2 KB"
    assert AgentUsage(pid=1, alive=False).line() == "cpu    n/a   ram      n/a   disk      n/a"


def test_cpu_percent_needs_two_samples() -> None:
    assert _cpu_percent(1.0, None, 2.0, None) is None
    # One core-second over one wall second is 100% of one core.
    assert _cpu_percent(2.0, 1.0, 2.0, 1.0) == 100.0


def test_ps_time_parses_minutes_hours_and_days() -> None:
    assert _parse_ps_time("01:02") == 62
    assert _parse_ps_time("01:02:03") == 3723
    assert _parse_ps_time("1-00:00:01") == 86401
    assert _parse_ps_time("nope") is None


def test_directory_size_sums_files(tmp_path) -> None:
    (tmp_path / "a.txt").write_bytes(b"abcd")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.txt").write_bytes(b"xy")
    assert directory_size(tmp_path) == 6


def test_sample_usage_reports_dead_process(monkeypatch) -> None:
    monkeypatch.setattr("coding_agent.resources.usage.process_alive", lambda pid: False)
    usage, cpu, _sampled = sample_usage(42)
    assert usage.alive is False
    assert cpu is None


def test_process_alive_rejects_init_and_missing() -> None:
    assert process_alive(0) is False
    assert process_alive(1) is False
    assert process_alive(999_999_999) is False
    assert process_alive(__import__("os").getpid()) is True
