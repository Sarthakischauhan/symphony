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
GATEWAY_MODELS = {
    "data": [
        {"id": "openai/gpt-realtime-2", "type": "realtime", "tags": ["websocket-realtime"]},
        {"id": "google/gemini-live", "type": "realtime", "tags": ["websocket-realtime"]},
        {"id": "spacexai/grok-voice-3.0", "type": "realtime", "tags": ["websocket-realtime"]},
        {"id": "other/voice", "type": "realtime", "tags": ["websocket-realtime"]},
        {"id": "openai/gpt-5", "type": "language", "tags": []},
    ]
}


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


def test_rendered_catalog_imports_and_reads_back_its_voices(tmp_path: Path) -> None:
    gen = load_generate_voice_models()
    catalog = gen.VoiceCatalog(gen.parse_realtime_spec(SPEC), (("eve", "Eve"), ("ara", "Ara")))
    output = tmp_path / "catalog.py"
    output.write_text(gen.render(catalog))
    namespace: dict[str, object] = {}
    exec(compile(output.read_text(), str(output), "exec"), namespace)
    models = namespace["VOICE_MODELS"]
    assert isinstance(models, tuple)
    assert [m.id for m in models] == ["grok-voice-latest", "grok-voice-3.0"]
    assert {m.default_voice for m in models} == {"eve"}
    assert output.read_text().startswith("# Generated by scripts/generate_voice_models.py. Do not edit by hand.")
    assert gen.read_existing_voices(output) == (("eve", "Eve"), ("ara", "Ara"))


def test_without_a_key_the_snapshot_voices_are_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gen = load_generate_voice_models()
    output = tmp_path / "catalog.py"
    output.write_text(gen.render(gen.VoiceCatalog(gen.parse_realtime_spec(SPEC), (("eve", "Eve"),))))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gen, "fetch_realtime_spec", lambda url: gen.parse_realtime_spec(SPEC))
    monkeypatch.setattr(gen, "fetch_openai_spec", lambda url: gen.parse_openai_spec(OPENAI_SPEC))
    monkeypatch.setattr(gen, "fetch_gateway_models", lambda url: gen.parse_gateway_models(GATEWAY_MODELS))
    catalog = gen.collect_catalog(output=output)
    assert catalog is not None and catalog.voices == (("eve", "Eve"),)
    assert catalog.gemini == ()


def test_unreachable_spec_keeps_the_snapshot_unless_strict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gen = load_generate_voice_models()

    def unreachable(url: str) -> object:
        raise OSError("offline")

    monkeypatch.setattr(gen, "fetch_realtime_spec", unreachable)
    assert gen.collect_catalog(output=tmp_path / "catalog.py") is None
    with pytest.raises(OSError):
        gen.collect_catalog(strict=True, output=tmp_path / "catalog.py")


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


def test_parse_gateway_and_gemini_models() -> None:
    gen = load_generate_voice_models()
    assert gen.parse_gateway_models(GATEWAY_MODELS) == (
        "openai/gpt-realtime-2",
        "google/gemini-live",
        "spacexai/grok-voice-3.0",
        "other/voice",
    )
    page = {
        "models": [
            {"name": "models/gemini-live", "supportedGenerationMethods": ["bidiGenerateContent"]},
            {"name": "models/gemini-pro", "supportedGenerationMethods": ["generateContent"]},
        ]
    }
    assert gen.parse_gemini_models(page) == ("gemini-live",)


def test_rendered_catalog_covers_every_provider(tmp_path: Path) -> None:
    gen = load_generate_voice_models()
    catalog = gen.VoiceCatalog(
        gen.parse_realtime_spec(SPEC),
        (("eve", "Eve"),),
        gen.parse_openai_spec(OPENAI_SPEC),
        gen.parse_gateway_models(GATEWAY_MODELS),
        ("gemini-live",),
    )
    output = tmp_path / "catalog.py"
    output.write_text(gen.render(catalog))
    namespace: dict[str, object] = {}
    exec(compile(output.read_text(), str(output), "exec"), namespace)
    models = namespace["VOICE_MODELS"]
    assert isinstance(models, tuple)
    by_id = {f"{m.provider}:{m.id}": m for m in models}
    assert list(by_id) == [
        "grok:grok-voice-latest",
        "grok:grok-voice-3.0",
        "openai:gpt-realtime",
        "openai:gpt-realtime-mini",
        "gemini:gemini-live",
        "vercel:openai/gpt-realtime-2",
        "vercel:google/gemini-live",
        "vercel:spacexai/grok-voice-3.0",
    ]
    assert by_id["vercel:openai/gpt-realtime-2"].default_voice == "alloy"
    assert by_id["vercel:spacexai/grok-voice-3.0"].default_voice == "eve"
    assert by_id["gemini:gemini-live"].voices == ()
    assert by_id["vercel:openai/gpt-realtime-2"].reasoning_efforts == ()
    assert gen.read_existing_voices(output) == (("eve", "Eve"),)
    assert gen.read_existing_gemini_models(output) == ("gemini-live",)
