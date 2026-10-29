from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_AI = Path(__file__).resolve().parents[1]
SCRIPT = CORE_AI / "scripts" / "generate_voice_models.py"

# The parts of https://docs.x.ai/voice-realtime.ws.json the script reads.
FORMAT = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["audio/pcm", "audio/pcmu", "audio/pcma", "audio/opus"]},
        "rate": {"type": "integer", "enum": [8000, 16000, 24000]},
    },
}
SPEC = {
    "clientMessages": [
        {"schema": {"properties": {"type": {"const": "input_audio_buffer.append"}}}, "example": {}},
        {
            "schema": {
                "properties": {
                    "session": {
                        "properties": {
                            "model": {"type": "string", "enum": ["grok-voice-latest", "grok-voice-3.0"]},
                            "reasoning": {"properties": {"effort": {"enum": ["high", "none"]}}},
                            "audio": {
                                "properties": {
                                    "input": {"properties": {"format": FORMAT}},
                                    "output": {"properties": {"format": FORMAT}},
                                }
                            },
                        }
                    }
                }
            },
            "example": {"session": {"voice": "Eve"}},
        },
    ]
}


def _pcm_option(rates: list[int]) -> dict:
    return {"properties": {"type": {"enum": ["audio/pcm"]}, "rate": {"enum": rates}}}


# The parts of OpenAI's openapi.json the script reads.
OPENAI_SPEC = {
    "components": {
        "schemas": {
            "RealtimeAudioFormats": {
                "anyOf": [
                    _pcm_option([24000]),
                    {"properties": {"type": {"enum": ["audio/pcmu"]}}},
                    {"properties": {"type": {"enum": ["audio/pcma"]}}},
                ]
            },
            "VoiceIdsShared": {"anyOf": [{"type": "string"}, {"type": "string", "enum": ["alloy", "marin"]}]},
            "RealtimeSessionCreateRequestGA": {
                "properties": {
                    "model": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "string",
                                "enum": [
                                    "gpt-realtime",
                                    "gpt-realtime-2025-08-28",
                                    "gpt-4o-realtime-preview",
                                    "gpt-realtime-mini",
                                    "gpt-4o-mini-transcribe",
                                ],
                            },
                        ]
                    },
                    "audio": {
                        "properties": {
                            "input": {"properties": {"format": {"$ref": "#/components/schemas/RealtimeAudioFormats"}}},
                            "output": {
                                "properties": {
                                    "format": {"$ref": "#/components/schemas/RealtimeAudioFormats"},
                                    "voice": {"$ref": "#/components/schemas/VoiceIdsShared", "default": "alloy"},
                                }
                            },
                        }
                    },
                }
            },
        }
    }
}
# Recorded from https://ai-gateway.vercel.sh/v1/models (trimmed).
GATEWAY_MODELS = {
    "data": [
        {
            "id": "openai/gpt-realtime-2",
            "type": "realtime",
            "tags": ["websocket-realtime"],
            "reasoning_options": [{"type": "effort", "values": ["minimal", "low", "medium", "high", "xhigh"]}],
        },
        {
            "id": "google/gemini-live",
            "type": "realtime",
            "tags": ["websocket-realtime"],
            "reasoning_options": [{"type": "effort", "values": ["low", "high"]}],
        },
        {
            "id": "spacexai/grok-voice-3.0",
            "type": "realtime",
            "tags": ["websocket-realtime"],
            "reasoning_options": [{"type": "toggle"}, {"type": "effort", "values": ["none", "low", "medium", "high"]}],
        },
        {"id": "other/voice", "type": "realtime", "tags": ["websocket-realtime"]},
        {"id": "openai/gpt-realtime-mini", "type": "realtime", "tags": None},
        {"id": "openai/gpt-5", "type": "language", "tags": []},
    ]
}
# Recorded from https://models.dev/api.json (trimmed).
MODELS_DEV = {
    "openai": {
        "models": {
            "gpt-realtime": {
                "type": "realtime",
                "reasoning_options": [{"type": "effort", "values": ["low", "minimal"]}],
            },
            "gpt-5": {"reasoning_options": [{"type": "effort", "values": ["low"]}]},
        }
    },
    "google": {
        "models": {
            "gemini-flash-live": {
                "type": "realtime",
                "reasoning_options": [{"type": "effort", "values": ["minimal", "low", "medium", "high"]}],
            },
            "gemini-flash-tts": {"type": "speech"},
        }
    },
    # models.dev lists no xAI realtime model: the realtime spec supplies them.
    "xai": {"models": {"grok-4": {"reasoning_options": []}}},
    # models.dev's Sarvam models are text models: the AsyncAPI spec supplies the realtime ones.
    "sarvam": {"models": {"sarvam-30b": {}}},
    "vercel": {
        "models": {
            "openai/gpt-realtime-2": {"type": "realtime"},
            "google/gemini-live": {"type": "realtime"},
            # Not tagged websocket-realtime by the gateway: skipped.
            "openai/gpt-realtime-mini": {"type": "realtime"},
            "fish/tts": {"type": "speech"},
        }
    },
}
# Recorded from https://ai.google.dev/gemini-api/docs/speech-generation.md.txt (trimmed).
GEMINI_TTS_DOC = """### Prebuilt voices

|---|---|---|
| **Zephyr** -- *Bright* | **Puck** -- *Upbeat* | **Kore** -- *Firm* |

### Extended Voice Library and filtering
"""
# Recorded from https://ai.google.dev/gemini-api/docs/live-guide.md.txt (trimmed).
GEMINI_LIVE_DOC = """Audio data in the Live API is always raw, little-endian,
16-bit PCM. Audio output always uses a sample rate of 24kHz. Input audio
is natively 16kHz, but the Live API will resample if needed
"""
# GET https://api.x.ai/v1/tts/voices response shape (trimmed).
XAI_VOICES = {"voices": [{"voice_id": "eve", "name": "Eve"}, {"voice_id": "ara", "name": "Ara"}]}
# The text-to-speech guide's voice table, trimmed to the markup the parser reads.
XAI_TTS_DOC = """
<tbody>
<tr><td><code>ara</code></td><td><div>Warm and friendly</div></td><td>voice_ara.mp3</td></tr>
<tr><td><code>eve</code></td><td><div>Energetic and upbeat</div><div>British<!-- --> accent</div></td><td>voice_eve.mp3</td></tr>
<tr><td><code>rex</code></td><td><div>Confident and clear</div></td><td>voice_rex.mp3</td></tr>
</tbody>
"""
# GET https://generativelanguage.googleapis.com/v1beta/voices and /models response shapes.
GEMINI_VOICES = {"voices": [{"id": "Zephyr", "displayName": "Zephyr"}, {"id": "Achird", "displayName": "Achird"}]}
GEMINI_MODELS_PAGES = [
    {
        "models": [{"name": "models/gemini-live-2", "supportedGenerationMethods": ["bidiGenerateContent"]}],
        "nextPageToken": "next",
    },
    {"models": [{"name": "models/gemini-pro", "supportedGenerationMethods": ["generateContent"]}]},
]


# The parts of https://docs.sarvam.ai/asyncapi.json the script reads (trimmed).
def _sarvam_ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/speechToTextRealtimeStreaming_{name}"}


SARVAM_ASYNCAPI = {
    "channels": {
        "/speech-to-text-realtime/ws": {
            "bindings": {
                "ws": {
                    "query": {
                        "properties": {
                            name: _sarvam_ref(name) for name in ("language_code", "model", "encoding", "sample_rate")
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "speechToTextRealtimeStreaming_language_code": {"type": "string", "enum": ["auto", "en-IN", "or-IN"]},
            "speechToTextRealtimeStreaming_model": {"type": "string", "enum": ["saaras:v3-realtime", "saaras:v4"]},
            "speechToTextRealtimeStreaming_encoding": {
                "type": "string",
                "enum": ["linear16", "linear32", "mulaw", "alaw"],
            },
            "speechToTextRealtimeStreaming_sample_rate": {"type": "string", "enum": ["16000", "8000"]},
        }
    },
}
SARVAM_GUIDE_URL = "https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices"
# The ``speaker`` description of https://docs.sarvam.ai/openapi/apis.json (trimmed).
SARVAM_SPEAKER_DESCRIPTION = f"""The speaker voice to be used for the output audio.

**Default:** shubh (for bulbul:v3), anushka (for bulbul:v2), shubh_enhi_ads (for bulbul:v4-flash).

**Model Compatibility (Speakers compatible with respective model):**
- **bulbul:v3:**
  - shubh (default), ritu
- **bulbul:v4-flash:**
  - 200+ persona voices. See the [Voices guide]({SARVAM_GUIDE_URL}#bulbul-v4-flash-voices) for the full catalog.
- **bulbul:v2:**
  - Female: anushka
  - Male: karun

**Note:** Speaker selection must match the chosen model version."""


def _nullable(name: str) -> dict:
    return {"oneOf": [{"$ref": f"#/components/schemas/{name}"}, {"type": "null"}]}


SARVAM_OPENAPI = {
    "paths": {
        "/text-to-speech": {
            "post": {
                "requestBody": {
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TextToSpeechRequest"}}}
                }
            }
        },
        "/speech-to-text": {
            "post": {
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "properties": {
                                    "model": _nullable("SpeechToTextModel"),
                                    "language_code": _nullable("SpeechToTextLanguage"),
                                }
                            }
                        }
                    }
                }
            }
        },
    },
    "components": {
        "schemas": {
            "TextToSpeechRequest": {
                "properties": {
                    "language_code": {"$ref": "#/components/schemas/TextToSpeechLanguage"},
                    "speaker": {**_nullable("TextToSpeechSpeaker"), "description": SARVAM_SPEAKER_DESCRIPTION},
                    "model": _nullable("TextToSpeechModel"),
                }
            },
            "TextToSpeechLanguage": {"type": "string", "enum": ["hi-IN", "od-IN"]},
            "TextToSpeechSpeaker": {"type": "string", "enum": ["anushka", "karun", "shubh", "ritu"]},
            "TextToSpeechModel": {"type": "string", "enum": ["bulbul:v2", "bulbul:v3", "bulbul:v4-flash"]},
            "SpeechToTextModel": {"type": "string", "enum": ["saaras:v3", "saaras:v4"]},
            "SpeechToTextLanguage": {"type": "string", "enum": ["unknown", "hi-IN"]},
        }
    },
}
# Recorded from the Voices guide's ``.md`` version (trimmed).
SARVAM_VOICES_DOC = """## Bulbul v3 Male Voices

## Bulbul v4 Flash Voices

### All v4 Flash voices

#### Hindi (hi-IN) (1 voices)

| Voice ID                  | Speaker | Style          |
| ------------------------- | ------- | -------------- |
| `aayan_hi_conversational` | Aayan   | conversational |

#### Hindi-English Code-Mixed (1 voices)

| Voice ID         | Speaker | Style |
| ---------------- | ------- | ----- |
| `shubh_enhi_ads` | Shubh   | ads   |

## Hear Voices Across Languages
"""


def load_generate_voice_models():
    spec = importlib.util.spec_from_file_location("generate_voice_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: its dataclasses resolve their module while being defined.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_realtime_spec_keeps_implemented_formats_and_orders_efforts() -> None:
    gen = load_generate_voice_models()
    spec = gen.parse_realtime_spec(json.loads(json.dumps(SPEC)))
    assert spec.models == ("grok-voice-latest", "grok-voice-3.0")
    assert spec.efforts == ("none", "high")
    assert spec.audio == (("pcm16", 24000), ("pcm16", 16000), ("pcm16", 8000), ("pcmu", 8000), ("pcma", 8000))
    assert spec.example_voice == "Eve"


def serve_fixtures(gen, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Answer the generator's fetches from the recorded fixtures; returns the URLs it asked for."""
    asked: list[str] = []
    documents = {
        gen.XAI_SPEC_URL: SPEC,
        gen.XAI_VOICES_URL: XAI_VOICES,
        gen.XAI_TTS_DOC_URL: XAI_TTS_DOC,
        gen.OPENAI_SPEC_URL: OPENAI_SPEC,
        gen.MODELS_DEV_URL: MODELS_DEV,
        gen.GATEWAY_MODELS_URL: GATEWAY_MODELS,
        gen.GEMINI_VOICES_URL: GEMINI_VOICES,
        gen.GEMINI_TTS_DOC_URL: GEMINI_TTS_DOC,
        gen.GEMINI_LIVE_DOC_URL: GEMINI_LIVE_DOC,
        gen.SARVAM_ASYNCAPI_URL: SARVAM_ASYNCAPI,
        gen.SARVAM_OPENAPI_URL: SARVAM_OPENAPI,
        f"{SARVAM_GUIDE_URL}.md": SARVAM_VOICES_DOC,
    }

    def get_json(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None) -> object:
        asked.append(url)
        if url == gen.GEMINI_MODELS_URL:
            return GEMINI_MODELS_PAGES[1 if params and params.get("pageToken") else 0]
        return documents[url]

    def get_text(url: str) -> object:
        asked.append(url)
        return documents[url]

    monkeypatch.setattr(gen, "get_json", get_json)
    monkeypatch.setattr(gen, "get_text", get_text)
    return asked


def load_rendered(gen, catalog, tmp_path: Path) -> dict:
    output = tmp_path / "catalog.py"
    output.write_text(gen.render(catalog))
    namespace: dict[str, object] = {}
    exec(compile(output.read_text(), str(output), "exec"), namespace)
    models = namespace["VOICE_MODELS"]
    assert isinstance(models, tuple)
    return {f"{m.provider}:{m.id}": m for m in models}


def test_without_keys_keyed_sources_are_skipped_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gen = load_generate_voice_models()
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    asked = serve_fixtures(gen, monkeypatch)
    by_id = load_rendered(gen, gen.collect_catalog(), tmp_path)
    assert gen.XAI_VOICES_URL not in asked and gen.GEMINI_VOICES_URL not in asked
    assert gen.GEMINI_MODELS_URL not in asked
    out = capsys.readouterr().out
    assert "XAI_API_KEY is not set: skipping https://api.x.ai/v1/tts/voices" in out
    assert "GEMINI_API_KEY is not set: skipping" in out
    assert "openai/gpt-realtime-2: gateway publishes efforts" in out
    assert "skipping gateway model other/voice" in out
    assert "skipping models.dev vercel model openai/gpt-realtime-mini" in out
    assert "grok-voice-latest: not a realtime model on models.dev" in out
    assert list(by_id) == [
        "grok:grok-voice-latest",
        "grok:grok-voice-3.0",
        "openai:gpt-realtime",
        "openai:gpt-realtime-mini",
        "gemini:gemini-flash-live",
        "vercel:openai/gpt-realtime-2",
        "vercel:google/gemini-live",
        "vercel:spacexai/grok-voice-3.0",
        "sarvam:saaras:v3-realtime",
        "sarvam:saaras:v4",
    ]
    assert "saaras:v3-realtime: not a realtime model on models.dev" in out
    sarvam = by_id["sarvam:saaras:v4"]
    assert sarvam.voices == () and sarvam.audio_output == ()
    assert [(a.encoding, a.sample_rate) for a in sarvam.audio_input] == [
        ("pcm16", 16000),
        ("pcm16", 8000),
        ("pcmu", 8000),
        ("pcma", 8000),
    ]
    assert sarvam.languages == ("auto", "en-IN", "or-IN")
    assert sarvam.sources.model == sarvam.sources.languages == gen.SARVAM_ASYNCAPI_URL
    grok = by_id["grok:grok-voice-latest"]
    assert [(v.id, v.label, v.traits) for v in grok.voices] == [
        ("ara", "Ara", ("Warm and friendly",)),
        ("eve", "Eve", ("Energetic and upbeat", "British accent")),
        ("rex", "Rex", ("Confident and clear",)),
    ]
    assert grok.default_voice == "eve"
    assert grok.sources.voices == gen.XAI_TTS_DOC_URL
    assert gen.XAI_TTS_DOC_URL in asked
    assert grok.reasoning_efforts == ("none", "high")
    openai = by_id["openai:gpt-realtime"]
    assert openai.reasoning_efforts == ("minimal", "low")
    assert openai.sources.reasoning_efforts == gen.MODELS_DEV_URL
    assert by_id["openai:gpt-realtime-mini"].sources.reasoning_efforts == ""
    assert openai.sources.model == gen.MODELS_DEV_URL
    assert by_id["openai:gpt-realtime-mini"].sources.model == gen.OPENAI_SPEC_URL
    assert grok.sources.model == gen.XAI_SPEC_URL
    assert by_id["vercel:openai/gpt-realtime-2"].sources.model == gen.MODELS_DEV_URL
    assert by_id["vercel:spacexai/grok-voice-3.0"].sources.model == gen.GATEWAY_MODELS_URL
    gemini = by_id["gemini:gemini-flash-live"]
    assert [(v.id, v.traits) for v in gemini.voices] == [
        ("Zephyr", ("Bright",)),
        ("Puck", ("Upbeat",)),
        ("Kore", ("Firm",)),
    ]
    assert gemini.default_voice == ""
    assert gemini.reasoning_efforts == ("minimal", "low", "medium", "high")
    assert [(a.encoding, a.sample_rate) for a in gemini.audio_input] == [("pcm16", 16000), ("pcm16", 24000)]
    assert [(a.encoding, a.sample_rate) for a in gemini.audio_output] == [("pcm16", 24000)]
    assert gemini.sources.model == gen.MODELS_DEV_URL
    assert gemini.sources.voices == gen.GEMINI_TTS_DOC_URL
    assert gemini.sources.audio == gen.GEMINI_LIVE_DOC_URL
    gateway_google = by_id["vercel:google/gemini-live"]
    assert gateway_google.voices == gemini.voices
    assert gateway_google.reasoning_efforts == ("low", "high")
    assert gateway_google.sources.reasoning_efforts == gen.GATEWAY_MODELS_URL
    assert by_id["vercel:openai/gpt-realtime-2"].reasoning_efforts == ()
    assert by_id["vercel:openai/gpt-realtime-2"].default_voice == "alloy"
    assert by_id["vercel:spacexai/grok-voice-3.0"].voices == grok.voices
    assert all(
        m.sources.model and m.sources.voices and m.sources.audio for m in by_id.values() if m.provider != "sarvam"
    )


def test_with_keys_the_keyed_sources_are_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gen = load_generate_voice_models()
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    asked = serve_fixtures(gen, monkeypatch)
    by_id = load_rendered(gen, gen.collect_catalog(), tmp_path)
    grok = by_id["grok:grok-voice-latest"]
    assert [v.id for v in grok.voices] == ["eve", "ara"]
    assert grok.sources.voices == gen.XAI_VOICES_URL
    assert gen.XAI_TTS_DOC_URL not in asked
    gemini = by_id["gemini:gemini-live-2"]
    assert gemini.sources.model == gen.GEMINI_MODELS_URL
    assert [v.id for v in gemini.voices] == ["Zephyr", "Achird"]
    assert gemini.sources.voices == gen.GEMINI_VOICES_URL
    assert "gemini:gemini-pro" not in by_id


def test_an_unreachable_source_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = load_generate_voice_models()

    def unreachable(url: str, headers: object = None, params: object = None) -> object:
        raise OSError("offline")

    monkeypatch.setattr(gen, "get_json", unreachable)
    with pytest.raises(OSError):
        gen.collect_catalog()


def test_a_doc_without_its_voice_table_raises() -> None:
    gen = load_generate_voice_models()
    with pytest.raises(ValueError):
        gen.parse_gemini_voice_table("### Prebuilt voices\n\nnothing here\n\n### Next\n")


def test_shipped_catalog_is_the_generated_one() -> None:
    gen = load_generate_voice_models()
    assert gen.OUTPUT.read_text().startswith("# Generated by scripts/generate_voice_models.py. Do not edit by hand.")


def test_parse_openai_spec_keeps_ga_realtime_aliases() -> None:
    gen = load_generate_voice_models()
    spec = gen.parse_openai_spec(OPENAI_SPEC)
    assert spec.models == ("gpt-realtime", "gpt-realtime-mini")
    assert spec.voices == ("alloy", "marin")
    assert spec.default_voice == "alloy"
    assert spec.audio == (("pcm16", 24000), ("pcmu", 8000), ("pcma", 8000))


def test_the_published_xai_voice_table_parses() -> None:
    """A verbatim excerpt of the real text-to-speech guide's voice table."""
    gen = load_generate_voice_models()
    html = (Path(__file__).parent / "fixtures/xai_tts_voice_table.html").read_text()
    voices = gen.parse_xai_voice_table(html)
    assert len(voices) == 28
    assert len({voice_id for voice_id, _, _ in voices}) == 28
    assert voices[0] == ("carina", "Carina", ("Soft, empathetic, and soothing",))
    assert all(traits for _, _, traits in voices)


def test_a_tts_guide_without_its_voice_table_raises() -> None:
    gen = load_generate_voice_models()
    with pytest.raises(ValueError):
        gen.parse_xai_voice_table("<html><body><p>no table</p></body></html>")


def test_sarvam_speech_models_come_from_the_openapi_spec_and_voices_guide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = load_generate_voice_models()
    serve_fixtures(gen, monkeypatch)
    output = tmp_path / "catalog.py"
    output.write_text(gen.render(gen.collect_catalog()))
    namespace: dict[str, object] = {}
    exec(compile(output.read_text(), str(output), "exec"), namespace)
    speech = namespace["SPEECH_MODELS"]
    assert isinstance(speech, tuple)
    by_id = {m.id: m for m in speech}
    assert [(m.id, m.kind) for m in speech] == [
        ("bulbul:v2", "tts"),
        ("bulbul:v3", "tts"),
        ("bulbul:v4-flash", "tts"),
        ("saaras:v3", "stt"),
        ("saaras:v4", "stt"),
    ]
    assert [(v.id, v.traits) for v in by_id["bulbul:v2"].voices] == [("anushka", ("Female",)), ("karun", ("Male",))]
    assert [v.id for v in by_id["bulbul:v3"].voices] == ["shubh", "ritu"]
    v4 = by_id["bulbul:v4-flash"]
    assert [(v.id, v.label, v.traits) for v in v4.voices] == [
        ("aayan_hi_conversational", "Aayan", ("conversational", "Hindi (hi-IN)")),
        ("shubh_enhi_ads", "Shubh", ("ads", "Hindi-English Code-Mixed")),
    ]
    assert v4.sources.voices == f"{SARVAM_GUIDE_URL}.md"
    assert [m.default_voice for m in speech] == ["anushka", "shubh", "shubh_enhi_ads", "", ""]
    assert by_id["bulbul:v3"].languages == ("hi-IN", "od-IN")
    assert by_id["saaras:v4"].languages == ("unknown", "hi-IN")
    assert by_id["saaras:v4"].sources.model == gen.SARVAM_OPENAPI_URL


def test_a_voices_guide_table_shorter_than_its_heading_raises() -> None:
    gen = load_generate_voice_models()
    doc = SARVAM_VOICES_DOC.replace("(1 voices)", "(2 voices)", 1)
    with pytest.raises(ValueError, match="heading says 2"):
        gen.sarvam_guide_voices(doc, "bulbul-v4-flash-voices")


def test_a_sarvam_speaker_missing_from_the_enum_raises() -> None:
    gen = load_generate_voice_models()
    with pytest.raises(ValueError, match="missing from the speaker enum"):
        gen.sarvam_tts_voices(SARVAM_SPEAKER_DESCRIPTION, ["anushka", "karun", "shubh"])
