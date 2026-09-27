"""CLI guards: URL scheme and a required chat model. No browser is launched."""

from __future__ import annotations

import pytest

from browser_agent.run.cli import main


def test_non_http_url_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Read it.", "--url", "ftp://example.test/file"]) == 2
    assert "http" in capsys.readouterr().err


def test_missing_credentials_exit_before_the_browser(capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    trace = tmp_path / "trace.json"
    argv = ["Search for travel and report the price.", "--url", "https://books.example/", "--trace", str(trace)]
    assert main(argv) == 2
    out, err = capsys.readouterr()
    assert "API_KEY" in err
    assert out == ""
    assert not trace.exists()
