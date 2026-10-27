"""The Gemini Live server messages this client reads, as typed models.

``BidiGenerateContentServerMessage`` in https://ai.google.dev/api/live: one of
``setupComplete``, ``serverContent``, ``toolCall``, ``goAway``, ``sessionResumptionUpdate``
(and more) at the top level, optionally with ``usageMetadata`` and ``voiceActivity``. Model
turns carry no response id; a turn runs until ``serverContent.turnComplete``.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class Incoming(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Blob(Incoming):
    data: str = ""
    mimeType: str = ""


class Part(Incoming):
    inlineData: Optional[Blob] = None


class Content(Incoming):
    parts: list[Part] = []


class Transcription(Incoming):
    text: str = ""


class ServerContent(Incoming):
    modelTurn: Optional[Content] = None
    turnComplete: bool = False
    interrupted: bool = False
    inputTranscription: Optional[Transcription] = None
    outputTranscription: Optional[Transcription] = None


class FunctionCall(Incoming):
    id: str
    name: str
    args: dict[str, Any] = {}


class ToolCallMessage(Incoming):
    functionCalls: list[FunctionCall] = []


class UsageMetadata(Incoming):
    promptTokenCount: Optional[int] = None
    responseTokenCount: Optional[int] = None


class VoiceActivity(Incoming):
    type: Literal["TYPE_UNSPECIFIED", "ACTIVITY_START", "ACTIVITY_END"] = "TYPE_UNSPECIFIED"


class SessionResumptionUpdate(Incoming):
    newHandle: str = ""
    resumable: bool = False


class ServerMessage(Incoming):
    setupComplete: Optional[dict[str, Any]] = None
    serverContent: Optional[ServerContent] = None
    toolCall: Optional[ToolCallMessage] = None
    usageMetadata: Optional[UsageMetadata] = None
    voiceActivity: Optional[VoiceActivity] = None
    sessionResumptionUpdate: Optional[SessionResumptionUpdate] = None
