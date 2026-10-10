"""Local failures are UI events, rendered as chips rather than chat text."""
from types import SimpleNamespace

from coding_agent.tui.transcript.messages import Notice
from coding_agent.tui.transcript.surface import NoticeEvent, TranscriptSurface
from coding_agent.tui.runtime.events import _failure_message


def test_notice_is_posted_then_rendered_by_event_handler():
    posted = []
    mounted = []
    app = SimpleNamespace(post_message=posted.append, _busy=False, _process=None,
                          _mount_transcript=mounted.append)
    TranscriptSurface.add_notice(app, "Microphone unavailable", "error")
    assert mounted == []
    assert len(posted) == 1
    assert isinstance(posted[0], NoticeEvent)
    TranscriptSurface.on_notice_event(app, posted[0])
    assert len(mounted) == 1
    chip = mounted[0]
    assert isinstance(chip, Notice)
    assert chip.has_class("notice-error")
    assert chip.archive_text() == "Microphone unavailable"


def test_ssl_failure_event_has_actionable_chip_text():
    text = _failure_message({"message": "[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac"})
    assert text == "SSL connection failed · bad record mac. Try the turn again."
