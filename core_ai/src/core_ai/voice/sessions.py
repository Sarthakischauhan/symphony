"""Live voice sessions by session id, so a run for that session can reach its connection."""

from core_ai.voice.session import VoiceSession


class VoiceSessions:
    def __init__(self) -> None:
        self._sessions: dict[str, VoiceSession] = {}

    def register(self, session_id: str, session: VoiceSession) -> None:
        self._sessions[session_id] = session

    def unregister(self, session_id: str, session: VoiceSession) -> None:
        if self._sessions.get(session_id) is session:
            del self._sessions[session_id]

    def get(self, session_id: str) -> VoiceSession | None:
        return self._sessions.get(session_id)


voice_sessions = VoiceSessions()
