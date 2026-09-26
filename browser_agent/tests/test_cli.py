"""CLI guards: URL scheme and the fixture notice. No browser is launched."""

from __future__ import annotations

import json

import pytest
from fakes import MemorySession

from browser_agent import cli


def test_non_http_url_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--url", "ftp://example.test/file", "--goal", "Read it."]) == 2
    assert "http" in capsys.readouterr().err


class FakeBrowser:
    """Stands in for Chromium: every URL opens the in-memory catalog."""

    async def start(self, *, headless: bool, sandbox: bool) -> None:
        assert sandbox is True

    async def open(self, url: str) -> MemorySession:
        return MemorySession(url=url)

    async def stop(self) -> None:
        return None


def test_fallback_notice_goes_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    monkeypatch.setattr(cli, "PlaywrightBrowser", FakeBrowser)
    trace = tmp_path / "trace.json"
    argv = ["run", "--url", "https://books.example/", "--goal", "Search for travel and report the price."]
    assert cli.main([*argv, "--trace", str(trace)]) == 0
    out, err = capsys.readouterr()
    assert "offline fixture policy" in err
    assert json.loads(out)["status"] == "done"
    assert json.loads(trace.read_text())["provider"] == "fixture"
