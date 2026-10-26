#!/usr/bin/env python3
"""Generate the shipped core_ai voice model catalog.

This is a maintainer command, not part of installing the package:

    uv run python scripts/generate_voice_models.py

It rewrites ``src/core_ai/voice/catalog.py`` from each provider's published
sources; commit the result.

- grok: xAI's realtime API spec (models, reasoning efforts, audio formats; no
  credentials) and, when ``XAI_API_KEY`` is set, the built-in voices of
  ``GET /v1/tts/voices``. Without a key the snapshot voices are kept.
- openai: OpenAI's published OpenAPI spec (``RealtimeSessionCreateRequestGA``:
  model ids, built-in voices, default voice, audio formats; no credentials).
- vercel: AI Gateway's public ``GET /v1/models`` (no credentials): realtime
  models tagged ``websocket-realtime``, the ones its realtime WebSocket serves.
- gemini: Live models need an API key to list (``GET /v1beta/models``, those
  supporting ``bidiGenerateContent``), so they are read only when
  ``GEMINI_API_KEY`` is set; without it the snapshot's Gemini models are kept.
  No API publishes Gemini's voices, so Gemini models carry none.

If a public source is unreachable the whole snapshot is kept unless
``CORE_AI_GENERATE_STRICT=1`` is set. ``CORE_AI_VOICE_SPEC=0`` skips the network.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "src/core_ai/voice/catalog.py"
REALTIME_SPEC_URL = "https://docs.x.ai/voice-realtime.ws.json"
XAI_BASE_URL = "https://api.x.ai/v1"
OPENAI_SPEC_URL = "https://raw.githubusercontent.com/openai/openai-openapi/main/openapi.json"
GATEWAY_MODELS_URL = "https://ai-gateway.vercel.sh/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Wire format types core_ai's grok realtime client implements (see
# core_ai/voice/grok/payload.py); `audio/opus` is published but not implemented.
ENCODINGS = {"audio/pcm": "pcm16", "audio/pcmu": "pcmu", "audio/pcma": "pcma"}
# The spec documents `rate` as PCM only; G.711 (pcmu/pcma) is 8 kHz.
G711_RATE = 8000
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high")
EXISTING_VOICE_RE = re.compile(r'VoiceInfo\("([^"]+)", "([^"]+)"')
EXISTING_GEMINI_RE = re.compile(r'id="([^"]+)",\n        provider="gemini"')
# OpenAI's realtime model enum also lists dated snapshots, beta-era previews and non-realtime
# audio models; the catalog keeps the GA realtime aliases.
OPENAI_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
# The tag AI Gateway puts on models its realtime WebSocket serves
# (https://vercel.com/docs/ai-gateway/capabilities/realtime).
GATEWAY_REALTIME_TAG = "websocket-realtime"
# Live audio is PCM16; input may be any rate (16 kHz native, resampled otherwise) and output is
# always 24 kHz (https://ai.google.dev/gemini-api/docs/live-api/capabilities).
GEMINI_AUDIO_INPUT = (("pcm16", 16000), ("pcm16", 24000))
GEMINI_AUDIO_OUTPUT = (("pcm16", 24000),)


@dataclass(frozen=True)
class RealtimeSpec:
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    audio: tuple[tuple[str, int], ...]
    example_voice: str


@dataclass(frozen=True)
class OpenAISpec:
    models: tuple[str, ...]
    voices: tuple[str, ...]
    default_voice: str
    audio: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class VoiceCatalog:
    spec: RealtimeSpec
    voices: tuple[tuple[str, str], ...]
    openai: OpenAISpec | None = None
    # AI Gateway model ids (``owner/model``).
    gateway: tuple[str, ...] = ()
    gemini: tuple[str, ...] = ()


def session_schema(payload: dict) -> dict:
    """The `session.update` client message's `session` schema."""
    for message in payload["clientMessages"]:
        properties = message["schema"]["properties"]
        if "session" in properties:
            return {"schema": properties["session"], "example": message["example"]["session"]}
    raise ValueError("realtime spec has no session.update message")


def audio_formats(fmt: dict) -> tuple[tuple[str, int], ...]:
    """Implemented (encoding, sample rate) pairs, 24 kHz PCM (the default) first."""
    rates = fmt["properties"]["rate"]["enum"]
    default = 24000
    found: list[tuple[str, int]] = []
    for wire in fmt["properties"]["type"]["enum"]:
        encoding = ENCODINGS.get(wire)
        if encoding == "pcm16":
            found.extend((encoding, rate) for rate in sorted(rates, key=lambda r: (r != default, -r)))
        elif encoding is not None:
            found.append((encoding, G711_RATE))
    return tuple(found)


def parse_realtime_spec(payload: dict) -> RealtimeSpec:
    session = session_schema(payload)
    properties = session["schema"]["properties"]
    efforts = properties["reasoning"]["properties"]["effort"]["enum"]
    audio = properties["audio"]["properties"]
    input_audio = audio_formats(audio["input"]["properties"]["format"])
    if input_audio != audio_formats(audio["output"]["properties"]["format"]):
        raise ValueError("input and output audio formats differ; the catalog needs both")
    return RealtimeSpec(
        models=tuple(properties["model"]["enum"]),
        efforts=tuple(sorted(efforts, key=EFFORT_ORDER.index)),
        audio=input_audio,
        example_voice=session["example"]["voice"],
    )


def fetch_realtime_spec(url: str = REALTIME_SPEC_URL) -> RealtimeSpec:
    import httpx

    response = httpx.get(url, headers={"User-Agent": "core-ai-voice-catalog/1.0"}, timeout=30.0)
    response.raise_for_status()
    return parse_realtime_spec(response.json())


def fetch_voices(api_key: str, base_url: str = XAI_BASE_URL) -> tuple[tuple[str, str], ...]:
    """Built-in voices as (voice_id, name), from `GET /v1/tts/voices`."""
    import httpx

    response = httpx.get(
        f"{base_url.rstrip('/')}/tts/voices",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    response.raise_for_status()
    voices = tuple((voice["voice_id"], voice["name"]) for voice in response.json()["voices"])
    if not voices:
        raise RuntimeError("/v1/tts/voices returned no voices")
    return voices


def read_existing_voices(path: Path = OUTPUT) -> tuple[tuple[str, str], ...]:
    """The snapshot's ``GROK_VOICES``."""
    if not path.exists():
        return ()
    text = path.read_text()
    start = text.find("GROK_VOICES: tuple")
    block = text[start : text.index("\n)\n", start)] if start >= 0 else ""
    return tuple(EXISTING_VOICE_RE.findall(block))


def read_existing_gemini_models(path: Path = OUTPUT) -> tuple[str, ...]:
    return tuple(EXISTING_GEMINI_RE.findall(path.read_text())) if path.exists() else ()


def _schemas(payload: dict) -> dict:
    return payload["components"]["schemas"]


def _resolve(schemas: dict, node: dict) -> dict:
    ref = node.get("$ref")
    return schemas[ref.rsplit("/", 1)[1]] if ref else node


def _enum_of(schemas: dict, node: dict) -> list[str]:
    """The string enum of a ``anyOf: [string, {enum}]`` schema (OpenAI's open enums)."""
    node = _resolve(schemas, node)
    for option in node.get("anyOf", ()):
        option = _resolve(schemas, option)
        if "enum" in option:
            return option["enum"]
        nested = _enum_of(schemas, option) if "anyOf" in option else []
        if nested:
            return nested
    return node.get("enum", [])


def openai_audio_formats(schemas: dict, node: dict) -> tuple[tuple[str, int], ...]:
    found: list[tuple[str, int]] = []
    for option in _resolve(schemas, node)["anyOf"]:
        properties = option["properties"]
        encoding = ENCODINGS.get(properties["type"]["enum"][0])
        if encoding == "pcm16":
            found.extend((encoding, rate) for rate in properties["rate"]["enum"])
        elif encoding is not None:
            found.append((encoding, G711_RATE))
    return tuple(found)


def parse_openai_spec(payload: dict) -> OpenAISpec:
    schemas = _schemas(payload)
    session = schemas["RealtimeSessionCreateRequestGA"]["properties"]
    models = tuple(
        model
        for model in _enum_of(schemas, session["model"])
        if "realtime" in model and "preview" not in model and not OPENAI_SNAPSHOT_RE.search(model)
    )
    audio = session["audio"]["properties"]
    input_audio = openai_audio_formats(schemas, audio["input"]["properties"]["format"])
    if input_audio != openai_audio_formats(schemas, audio["output"]["properties"]["format"]):
        raise ValueError("OpenAI input and output audio formats differ; the catalog needs both")
    voice = audio["output"]["properties"]["voice"]
    return OpenAISpec(
        models=models,
        voices=tuple(_enum_of(schemas, voice)),
        default_voice=voice["default"],
        audio=input_audio,
    )


def parse_gateway_models(payload: dict) -> tuple[str, ...]:
    return tuple(
        model["id"]
        for model in payload["data"]
        if model.get("type") == "realtime" and GATEWAY_REALTIME_TAG in model.get("tags", ())
    )


def parse_gemini_models(payload: dict) -> tuple[str, ...]:
    return tuple(
        model["name"].removeprefix("models/")
        for model in payload.get("models", ())
        if "bidiGenerateContent" in model.get("supportedGenerationMethods", ())
    )


def _get_json(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None) -> dict:
    import httpx

    response = httpx.get(
        url,
        headers={"User-Agent": "core-ai-voice-catalog/1.0", **(headers or {})},
        params=params,
        timeout=60.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def fetch_openai_spec(url: str = OPENAI_SPEC_URL) -> OpenAISpec:
    return parse_openai_spec(_get_json(url))


def fetch_gateway_models(url: str = GATEWAY_MODELS_URL) -> tuple[str, ...]:
    return parse_gateway_models(_get_json(url))


def fetch_gemini_models(api_key: str, url: str = GEMINI_MODELS_URL) -> tuple[str, ...]:
    models: list[str] = []
    params = {"pageSize": "1000"}
    while True:
        page = _get_json(url, headers={"x-goog-api-key": api_key}, params=params)
        models.extend(parse_gemini_models(page))
        token = page.get("nextPageToken")
        if not token:
            return tuple(models)
        params = {"pageSize": "1000", "pageToken": token}


def default_voice(spec: RealtimeSpec, voices: tuple[tuple[str, str], ...]) -> str:
    """The voice the spec's own session example uses (`Eve`), as a catalog id."""
    wanted = spec.example_voice.lower()
    return next(voice_id for voice_id, label in voices if wanted in (voice_id.lower(), label.lower()))


def quoted(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(json.dumps(v) for v in values) + ("," if len(values) == 1 else "") + ")"


@dataclass(frozen=True)
class ModelFamily:
    """How a catalog entry refers to its provider's shared voices and audio formats."""

    voices: str
    default_voice: str
    audio_input: str
    audio_output: str


def model_lines(model_id: str, provider: str, family: ModelFamily, efforts: tuple[str, ...]) -> tuple[str, ...]:
    return (
        "    VoiceModelSpec(",
        f"        id={json.dumps(model_id)},",
        f"        provider={json.dumps(provider)},",
        f"        voices={family.voices},",
        f"        default_voice={json.dumps(family.default_voice)},",
        f"        audio_input={family.audio_input},",
        f"        audio_output={family.audio_output},",
        f"        reasoning_efforts={quoted(efforts)},",
        "    ),",
    )


def audio_lines(name: str, formats: tuple[tuple[str, int], ...]) -> list[str]:
    return [
        f"{name}: tuple[AudioFormat, ...] = (",
        *(f"    AudioFormat({json.dumps(encoding)}, {rate})," for encoding, rate in formats),
        ")",
        "",
    ]


def voice_lines(name: str, voices: tuple[tuple[str, str], ...]) -> list[str]:
    return [
        f"{name}: tuple[VoiceInfo, ...] = (",
        *(f"    VoiceInfo({json.dumps(voice_id)}, {json.dumps(label)})," for voice_id, label in voices),
        ")",
        "",
    ]


def families(catalog: VoiceCatalog) -> dict[str, ModelFamily]:
    """Catalog provider (and AI Gateway owner) -> its voices and formats."""
    grok = ModelFamily(
        "GROK_VOICES", default_voice(catalog.spec, catalog.voices), "GROK_VOICE_AUDIO", "GROK_VOICE_AUDIO"
    )
    found = {
        "grok": grok,
        "spacexai": grok,
        "gemini": ModelFamily("()", "", "GEMINI_VOICE_AUDIO_INPUT", "GEMINI_VOICE_AUDIO_OUTPUT"),
    }
    found["google"] = found["gemini"]
    if catalog.openai is not None:
        found["openai"] = ModelFamily(
            "OPENAI_VOICES", catalog.openai.default_voice, "OPENAI_VOICE_AUDIO", "OPENAI_VOICE_AUDIO"
        )
    return found


def gateway_models(catalog: VoiceCatalog) -> tuple[tuple[str, ModelFamily], ...]:
    """Gateway models whose upstream provider's voices and formats the catalog has.

    The gateway passes voice and audio format through to that provider. Reasoning effort has
    no field in the normalized session config, so gateway entries list none.
    """
    known = families(catalog)
    return tuple(
        (model_id, known[model_id.split("/", 1)[0]])
        for model_id in catalog.gateway
        if model_id.split("/", 1)[0] in known
    )


def render(catalog: VoiceCatalog) -> str:
    spec = catalog.spec
    known = families(catalog)
    lines = [
        "# Generated by scripts/generate_voice_models.py. Do not edit by hand.",
        '"""Realtime voice models, by provider:',
        "",
        f"- grok: xAI's realtime API spec ({REALTIME_SPEC_URL}) and ``GET /v1/tts/voices``.",
        f"- openai: OpenAI's OpenAPI spec ({OPENAI_SPEC_URL}).",
        f"- vercel: AI Gateway's realtime WebSocket models ({GATEWAY_MODELS_URL}).",
        f"- gemini: Live models from ``{GEMINI_MODELS_URL}`` (needs an API key; none publish voices).",
        '"""',
        "",
        "from core_ai.voice.types import AudioFormat, VoiceInfo, VoiceModelSpec",
        "",
        *voice_lines("GROK_VOICES", catalog.voices),
        *audio_lines("GROK_VOICE_AUDIO", spec.audio),
    ]
    if catalog.openai is not None:
        lines.extend(voice_lines("OPENAI_VOICES", tuple((voice, voice.title()) for voice in catalog.openai.voices)))
        lines.extend(audio_lines("OPENAI_VOICE_AUDIO", catalog.openai.audio))
    lines.extend(audio_lines("GEMINI_VOICE_AUDIO_INPUT", GEMINI_AUDIO_INPUT))
    lines.extend(audio_lines("GEMINI_VOICE_AUDIO_OUTPUT", GEMINI_AUDIO_OUTPUT))
    lines.append("VOICE_MODELS: tuple[VoiceModelSpec, ...] = (")
    for model_id in spec.models:
        lines.extend(model_lines(model_id, "grok", known["grok"], spec.efforts))
    for model_id in catalog.openai.models if catalog.openai is not None else ():
        lines.extend(model_lines(model_id, "openai", known["openai"], ()))
    for model_id in catalog.gemini:
        lines.extend(model_lines(model_id, "gemini", known["gemini"], ()))
    for model_id, family in gateway_models(catalog):
        lines.extend(model_lines(model_id, "vercel", family, ()))
    lines.extend((")", ""))
    return "\n".join(lines)


def collect_catalog(*, strict: bool = False, output: Path = OUTPUT) -> VoiceCatalog | None:
    """The catalog to write, or None to keep the existing snapshot."""
    if os.environ.get("CORE_AI_VOICE_SPEC", "1") == "0":
        return None
    try:
        spec = fetch_realtime_spec(os.environ.get("CORE_AI_VOICE_SPEC_URL", REALTIME_SPEC_URL))
        openai = fetch_openai_spec(os.environ.get("CORE_AI_OPENAI_SPEC_URL", OPENAI_SPEC_URL))
        gateway = fetch_gateway_models(os.environ.get("CORE_AI_GATEWAY_MODELS_URL", GATEWAY_MODELS_URL))
    except Exception:
        if strict:
            raise
        return None
    api_key = os.environ.get("XAI_API_KEY")
    if api_key:
        voices = fetch_voices(api_key, os.environ.get("XAI_BASE_URL", XAI_BASE_URL))
    else:
        voices = read_existing_voices(output)
        if not voices:
            raise RuntimeError("no snapshot voices to keep; set XAI_API_KEY to read /v1/tts/voices")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    gemini = fetch_gemini_models(gemini_key) if gemini_key else read_existing_gemini_models(output)
    return VoiceCatalog(spec, voices, openai, gateway, gemini)


def generate(*, strict: bool = False, output: Path = OUTPUT) -> Path:
    catalog = collect_catalog(strict=strict, output=output)
    if catalog is None:
        print(f"kept the existing snapshot at {output}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(catalog))
    count = sum(1 for line in output.read_text().splitlines() if line == "    VoiceModelSpec(")
    print(f"wrote {count} voice models to {output}")
    return output


def main() -> None:
    # Local development credentials are only loaded for direct script runs;
    # explicit environment variables still win over values from .env.
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    generate(strict=os.environ.get("CORE_AI_GENERATE_STRICT") == "1")


if __name__ == "__main__":
    main()
