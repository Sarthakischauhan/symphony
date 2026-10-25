"""Voice models, kept out of the default text catalog. Hand-written: the generated
catalog only covers text models.

Voices and traits follow the xAI voice docs
(https://docs.x.ai/developers/model-capabilities/audio/voice-agent#available-voices).
"""

from core_ai.voice.types import AudioFormat, VoiceInfo, VoiceModelSpec

GROK_VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo("eve", "Eve", ("energetic", "upbeat", "British accent")),
    VoiceInfo("ara", "Ara", ("warm", "friendly")),
    VoiceInfo("sal", "Sal", ("smooth", "balanced")),
    VoiceInfo("leo", "Leo", ("authoritative", "strong", "British accent")),
    VoiceInfo("rex", "Rex", ("confident", "clear")),
    VoiceInfo("carina", "Carina", ("soft", "empathetic", "soothing")),
    VoiceInfo("zagan", "Zagan", ("powerful", "dramatic", "unmistakable")),
    VoiceInfo("helix", "Helix", ("bold", "dynamic", "adrenaline-fueled")),
    VoiceInfo("orion", "Orion", ("rich", "cinematic", "resonant")),
    VoiceInfo("luna", "Luna", ("gentle", "patient", "deeply nurturing")),
    VoiceInfo("iris", "Iris", ("friendly", "upbeat", "naturally charming")),
    VoiceInfo("altair", "Altair", ("elegant", "refined", "effortlessly premium")),
    VoiceInfo("zenith", "Zenith", ("sharp", "focused", "driven")),
    VoiceInfo("perseus", "Perseus", ("strong", "confident", "trustworthy")),
    VoiceInfo("helios", "Helios", ("upbeat", "energetic", "endlessly versatile")),
    VoiceInfo("lux", "Lux", ("grounded", "calm", "quietly wise")),
    VoiceInfo("kepler", "Kepler", ("inventive", "forward-thinking", "charismatic")),
    VoiceInfo("rigel", "Rigel", ("precise", "professional", "calmly confident", "Australian accent")),
    VoiceInfo("cosmo", "Cosmo", ("bright", "curious", "easy to follow")),
    VoiceInfo("celeste", "Celeste", ("compassionate", "confident", "reassuring")),
    VoiceInfo("ursa", "Ursa", ("friendly", "warm", "steadfast")),
    VoiceInfo("sirius", "Sirius", ("quick-witted", "clever", "playful")),
    VoiceInfo("lumen", "Lumen", ("warm", "articulate", "engaging")),
    VoiceInfo("castor", "Castor", ("charismatic", "down-to-earth", "easygoing")),
    VoiceInfo("naksh", "Naksh", ("warm", "thoughtful", "wise", "Indian accent")),
    VoiceInfo("atlas", "Atlas", ("confident", "commanding", "reassuring")),
    VoiceInfo("aurora", "Aurora", ("serene", "steady", "radiant")),
    VoiceInfo("liora", "Liora", ("calm", "grounded", "luminous")),
)

GROK_VOICE_AUDIO: tuple[AudioFormat, ...] = (
    AudioFormat("pcm16", 24000),
    AudioFormat("pcm16", 16000),
    AudioFormat("pcm16", 8000),
    AudioFormat("pcmu", 8000),
    AudioFormat("pcma", 8000),
)


def _grok_voice_model(model_id: str) -> VoiceModelSpec:
    return VoiceModelSpec(
        id=model_id,
        provider="grok",
        voices=GROK_VOICES,
        default_voice="eve",
        audio_input=GROK_VOICE_AUDIO,
        audio_output=GROK_VOICE_AUDIO,
        reasoning_efforts=("none", "high"),
    )


VOICE_MODELS: tuple[VoiceModelSpec, ...] = (
    _grok_voice_model("grok-voice-3.0"),
    _grok_voice_model("grok-voice-latest"),
)
