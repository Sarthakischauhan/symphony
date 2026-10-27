#!/usr/bin/env python3
"""Generate the shipped core_ai voice model catalog.

This is a maintainer command, not part of installing the package:

    uv run python scripts/generate_voice_models.py

It rewrites ``src/core_ai/voice/catalog.py`` from each provider's published sources and
records, on every entry, the source of its model id, voices, efforts and audio formats.
Nothing is carried over from the previous catalog and nothing is filled in by hand: a value
no source publishes is left out.

- grok: xAI's realtime API spec (models, efforts, audio formats, the session example's
  voice) and the built-in voices of the text-to-speech guide's voice table. With
  ``XAI_API_KEY``, ``GET /v1/tts/voices`` replaces that table.
- openai: OpenAI's OpenAPI spec (models, voices, default voice, audio formats) and
  models.dev (reasoning efforts).
- gemini: Live models from models.dev and, with ``GEMINI_API_KEY``, ``GET /v1beta/models``;
  efforts from models.dev; voices from the speech-generation guide's prebuilt voice table
  (which the Live guide says native-audio models use) and, with ``GEMINI_API_KEY``, the
  prebuilt voices of ``GET /v1beta/voices``; audio formats from the Live guide.
- vercel: AI Gateway's public ``GET /v1/models`` (realtime WebSocket models and their
  efforts); voices and audio formats are the upstream provider's, which the gateway passes
  through. Efforts are kept only where the gateway documents how to send them.

A source that needs a missing key is skipped with a log line. Any other failure raises.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "src/core_ai/voice/catalog.py"
XAI_SPEC_URL = "https://docs.x.ai/voice-realtime.ws.json"
XAI_VOICES_URL = "https://api.x.ai/v1/tts/voices"
XAI_TTS_DOC_URL = "https://docs.x.ai/developers/model-capabilities/audio/text-to-speech"
OPENAI_SPEC_URL = "https://raw.githubusercontent.com/openai/openai-openapi/main/openapi.json"
MODELS_DEV_URL = "https://models.dev/api.json"
GATEWAY_MODELS_URL = "https://ai-gateway.vercel.sh/v1/models"
GATEWAY_REALTIME_DOC_URL = "https://vercel.com/docs/ai-gateway/capabilities/realtime"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_VOICES_URL = "https://generativelanguage.googleapis.com/v1beta/voices"
GEMINI_TTS_DOC_URL = "https://ai.google.dev/gemini-api/docs/speech-generation.md.txt"
GEMINI_LIVE_DOC_URL = "https://ai.google.dev/gemini-api/docs/live-guide.md.txt"

# Wire format types core_ai's realtime clients implement; `audio/opus` is published but not
# implemented.
ENCODINGS = {"audio/pcm": "pcm16", "audio/pcmu": "pcmu", "audio/pcma": "pcma"}
# Neither spec gives G.711 (pcmu/pcma) a rate: G.711 itself is defined at 8 kHz.
G711_RATE = 8000
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh")
# OpenAI's realtime model enum also lists dated snapshots, beta-era previews and non-realtime
# audio models; the catalog keeps the GA realtime aliases.
OPENAI_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
# The tag AI Gateway puts on models its realtime WebSocket serves (GATEWAY_REALTIME_DOC_URL).
GATEWAY_REALTIME_TAG = "websocket-realtime"
# Gateway owners whose reasoning effort the realtime docs say how to send
# (``providerOptions.google.thinkingConfig.thinkingLevel``); see core_ai/voice/vercel/payload.py.
GATEWAY_EFFORT_OWNERS = ("google",)
# Catalog provider for each gateway owner, whose voices and audio formats the gateway passes on.
GATEWAY_UPSTREAM = {"openai": "openai", "google": "gemini", "spacexai": "grok"}
GEMINI_VOICE_RE = re.compile(r"\*\*(\w+)\*\* -- \*([^*]+)\*")
GEMINI_OUTPUT_RATE_RE = re.compile(r"output always uses a sample rate of (\d+)kHz")
GEMINI_INPUT_RATE_RE = re.compile(r"Input audio\s+is natively (\d+)kHz")

Voice = tuple[str, str, tuple[str, ...]]
Audio = tuple[tuple[str, int], ...]


def log(message: str) -> None:
    print(f"generate_voice_models: {message}")


@dataclass(frozen=True)
class Sourced:
    """Values and the URL they were read from."""

    values: tuple
    source: str


@dataclass(frozen=True)
class Family:
    """A provider's shared voices and audio formats, with their sources."""

    voices: Sourced
    default_voice: str
    audio_input: Sourced
    audio_output: Sourced


@dataclass(frozen=True)
class Entry:
    id: str
    provider: str
    family: str
    model_source: str
    efforts: Sourced = field(default_factory=lambda: Sourced((), ""))


@dataclass(frozen=True)
class VoiceCatalog:
    families: dict[str, Family]
    entries: tuple[Entry, ...]


# --- xAI ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RealtimeSpec:
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    audio: Audio
    example_voice: str


def session_schema(payload: dict) -> dict:
    """The `session.update` client message's `session` schema."""
    for message in payload["clientMessages"]:
        properties = message["schema"]["properties"]
        if "session" in properties:
            return {"schema": properties["session"], "example": message["example"]["session"]}
    raise ValueError("realtime spec has no session.update message")


def audio_formats(fmt: dict) -> Audio:
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
        efforts=ordered_efforts(efforts),
        audio=input_audio,
        example_voice=session["example"]["voice"],
    )


def parse_xai_voices(payload: dict) -> tuple[Voice, ...]:
    voices = tuple((voice["voice_id"], voice["name"], ()) for voice in payload["voices"])
    if not voices:
        raise ValueError("/v1/tts/voices returned no voices")
    return voices


def parse_xai_voice_table(html: str) -> tuple[Voice, ...]:
    """The guide's voice table is rendered only into its HTML: the page's ``.md`` version omits
    it and the page embeds no JSON data for it, so the rendered table is read. Voices from the text-to-speech guide's table: id, capitalised label, tone and accent."""
    body = html.split("<tbody>", 1)[-1]
    rows = re.findall(r"<tr>(.*?)</tr>", body, flags=re.DOTALL)
    voices: list[Voice] = []
    for row in rows:
        found = re.search(r"<code>([a-z0-9_-]+)</code>", row)
        if found is None or "voice_" not in row:
            continue
        voice_id = found.group(1)
        tone = re.search(r"<div>(.*?)</div>", row, flags=re.DOTALL)
        text = re.sub(r"<span\b.*?</span>", "", tone.group(1) if tone else "", flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text).replace("&amp;", "&").strip()
        traits = (text,) if text else ()
        accent = re.search(r">([A-Za-z]+)<!-- --> accent<", row)
        if accent:
            traits += (f"{accent.group(1)} accent",)
        voices.append((voice_id, voice_id[:1].upper() + voice_id[1:], traits))
    if not voices:
        raise ValueError("text-to-speech guide published no voice table")
    return tuple(voices)


def grok_family(spec: RealtimeSpec, voices: Sourced) -> Family:
    audio = Sourced(spec.audio, XAI_SPEC_URL)
    return Family(voices, spec.example_voice.lower(), audio, audio)


# --- OpenAI ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenAISpec:
    models: tuple[str, ...]
    voices: tuple[str, ...]
    default_voice: str
    audio: Audio


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


def openai_audio_formats(schemas: dict, node: dict) -> Audio:
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
    schemas = payload["components"]["schemas"]
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


def openai_family(spec: OpenAISpec) -> Family:
    audio = Sourced(spec.audio, OPENAI_SPEC_URL)
    voices = tuple((voice, voice.title(), ()) for voice in spec.voices)
    return Family(Sourced(voices, OPENAI_SPEC_URL), spec.default_voice, audio, audio)


# --- models.dev and AI Gateway -------------------------------------------------------------


def ordered_efforts(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=EFFORT_ORDER.index))


def published_efforts(model: dict) -> tuple[str, ...]:
    """The ``effort`` values of a models.dev or gateway ``reasoning_options`` list."""
    for option in model.get("reasoning_options") or ():
        if option["type"] == "effort":
            return ordered_efforts(option["values"])
    return ()


def parse_models_dev(payload: dict, provider: str) -> dict[str, tuple[str, ...]]:
    """A models.dev provider's realtime models -> their efforts."""
    return {
        model_id: published_efforts(model)
        for model_id, model in payload[provider]["models"].items()
        if model.get("type") == "realtime"
    }


def parse_gateway_models(payload: dict) -> dict[str, tuple[str, ...]]:
    """Gateway realtime WebSocket models -> their published efforts."""
    return {
        model["id"]: published_efforts(model)
        for model in payload["data"]
        if model.get("type") == "realtime" and GATEWAY_REALTIME_TAG in (model.get("tags") or ())
    }


def gateway_entries(models: dict[str, tuple[str, ...]], families: dict[str, Family]) -> tuple[Entry, ...]:
    entries: list[Entry] = []
    for model_id, efforts in models.items():
        owner = model_id.split("/", 1)[0]
        upstream = GATEWAY_UPSTREAM.get(owner)
        if upstream is None:
            log(f"skipping gateway model {model_id}: no catalog provider supplies {owner!r} voices")
            continue
        if efforts and owner not in GATEWAY_EFFORT_OWNERS:
            log(f"{model_id}: gateway publishes efforts {efforts} but documents no realtime field to send them")
            efforts = ()
        sourced = Sourced(efforts, GATEWAY_MODELS_URL if efforts else "")
        entries.append(Entry(model_id, "vercel", upstream, GATEWAY_MODELS_URL, sourced))
    return tuple(entries)


# --- Gemini ------------------------------------------------------------------------------


def parse_gemini_voice_table(text: str) -> tuple[Voice, ...]:
    """The speech-generation guide's ``### Prebuilt voices`` table: (name, name, (trait,))."""
    start = text.index("### Prebuilt voices")
    table = text[start : text.index("\n### ", start + 1)]
    voices = tuple((name, name, (trait,)) for name, trait in GEMINI_VOICE_RE.findall(table))
    if not voices:
        raise ValueError("speech-generation guide has no prebuilt voices")
    return voices


def parse_gemini_voices(payload: dict) -> tuple[Voice, ...]:
    """Prebuilt voices of ``GET /v1beta/voices``."""
    return tuple((voice["id"], voice["displayName"], ()) for voice in payload.get("voices", ()))


def parse_gemini_audio(text: str) -> tuple[Audio, Audio]:
    """(input, output) PCM16 rates from the Live guide's audio formats section."""
    output = int(GEMINI_OUTPUT_RATE_RE.search(text)[1]) * 1000
    native = int(GEMINI_INPUT_RATE_RE.search(text)[1]) * 1000
    inputs = tuple(("pcm16", rate) for rate in dict.fromkeys((native, output)))
    return inputs, (("pcm16", output),)


def parse_gemini_models(payload: dict) -> tuple[str, ...]:
    return tuple(
        model["name"].removeprefix("models/")
        for model in payload.get("models", ())
        if "bidiGenerateContent" in model.get("supportedGenerationMethods", ())
    )


def gemini_family(voices: Sourced, live_doc: str) -> Family:
    inputs, outputs = parse_gemini_audio(live_doc)
    # Google publishes no default voice; leave it to the caller's choice from the list.
    return Family(voices, "", Sourced(inputs, GEMINI_LIVE_DOC_URL), Sourced(outputs, GEMINI_LIVE_DOC_URL))


# --- fetching ------------------------------------------------------------------------------


def _get(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None):
    import httpx

    response = httpx.get(
        url,
        headers={"User-Agent": "core-ai-voice-catalog/1.0", **(headers or {})},
        params=params,
        timeout=60.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


def get_json(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None) -> dict:
    return _get(url, headers, params).json()


def get_text(url: str) -> str:
    return _get(url).text


def get_gemini_pages(url: str, api_key: str, params: dict[str, str]) -> list[dict]:
    pages: list[dict] = []
    query = dict(params)
    while True:
        page = get_json(url, headers={"x-goog-api-key": api_key}, params=query)
        pages.append(page)
        token = page.get("nextPageToken")
        if not token:
            return pages
        query["pageToken"] = token


def keyed(name: str, what: str) -> str | None:
    key = os.environ.get(name)
    if not key:
        log(f"{name} is not set: skipping {what}")
    return key


def collect_catalog() -> VoiceCatalog:
    spec = parse_realtime_spec(get_json(XAI_SPEC_URL))
    # ``/v1/tts/voices`` is the roster; without a key the text-to-speech guide's voice table is,
    # and the guide is not fetched at all when the live API answers.
    xai_key = keyed("XAI_API_KEY", f"{XAI_VOICES_URL} (using the voice table of {XAI_TTS_DOC_URL})")
    grok_voices = (
        Sourced(
            parse_xai_voices(get_json(XAI_VOICES_URL, headers={"Authorization": f"Bearer {xai_key}"})), XAI_VOICES_URL
        )
        if xai_key
        else Sourced(parse_xai_voice_table(get_text(XAI_TTS_DOC_URL)), XAI_TTS_DOC_URL)
    )
    openai = parse_openai_spec(get_json(OPENAI_SPEC_URL))
    models_dev = get_json(MODELS_DEV_URL)
    gemini_key = keyed("GEMINI_API_KEY", f"{GEMINI_MODELS_URL} and {GEMINI_VOICES_URL}")
    gemini_voices = Sourced(parse_gemini_voice_table(get_text(GEMINI_TTS_DOC_URL)), GEMINI_TTS_DOC_URL)
    gemini_models = {model_id: MODELS_DEV_URL for model_id in parse_models_dev(models_dev, "google")}
    if gemini_key:
        pages = get_gemini_pages(GEMINI_VOICES_URL, gemini_key, {"type": "prebuilt", "pageSize": "1000"})
        gemini_voices = Sourced(tuple(v for page in pages for v in parse_gemini_voices(page)), GEMINI_VOICES_URL)
        for page in get_gemini_pages(GEMINI_MODELS_URL, gemini_key, {"pageSize": "1000"}):
            gemini_models.update(dict.fromkeys(parse_gemini_models(page), GEMINI_MODELS_URL))
    families = {
        "grok": grok_family(spec, grok_voices),
        "openai": openai_family(openai),
        "gemini": gemini_family(gemini_voices, get_text(GEMINI_LIVE_DOC_URL)),
    }
    return VoiceCatalog(
        families,
        provider_entries(
            spec, openai, parse_models_dev(models_dev, "openai"), parse_models_dev(models_dev, "google"), gemini_models
        )
        + gateway_entries(parse_gateway_models(get_json(GATEWAY_MODELS_URL)), families),
    )


def provider_entries(
    spec: RealtimeSpec,
    openai: OpenAISpec,
    openai_efforts: dict[str, tuple[str, ...]],
    gemini_efforts: dict[str, tuple[str, ...]],
    gemini_models: dict[str, str],
) -> tuple[Entry, ...]:
    """Direct-provider entries, each with the source of its id and efforts."""
    grok = tuple(Entry(m, "grok", "grok", XAI_SPEC_URL, Sourced(spec.efforts, XAI_SPEC_URL)) for m in spec.models)
    return (
        grok
        + tuple(
            Entry(m, "openai", "openai", OPENAI_SPEC_URL, models_dev_efforts(openai_efforts, m)) for m in openai.models
        )
        + tuple(
            Entry(m, "gemini", "gemini", src, models_dev_efforts(gemini_efforts, m)) for m, src in gemini_models.items()
        )
    )


def models_dev_efforts(efforts: dict[str, tuple[str, ...]], model_id: str) -> Sourced:
    values = efforts.get(model_id, ())
    return Sourced(values, MODELS_DEV_URL if values else "")


# --- rendering -----------------------------------------------------------------------------


def quoted(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(json.dumps(v) for v in values) + ("," if len(values) == 1 else "") + ")"


def family_lines(name: str, family: Family) -> list[str]:
    prefix = name.upper()
    return [
        f"# {family.voices.source}",
        f"{prefix}_VOICES: tuple[VoiceInfo, ...] = (",
        *(
            f"    VoiceInfo({json.dumps(voice_id)}, {json.dumps(label)}, {quoted(traits)}),"
            for voice_id, label, traits in family.voices.values
        ),
        ")",
        f"# {family.audio_input.source}",
        f"{prefix}_AUDIO_INPUT: tuple[AudioFormat, ...] = (",
        *(f"    AudioFormat({json.dumps(e)}, {rate})," for e, rate in family.audio_input.values),
        ")",
        f"{prefix}_AUDIO_OUTPUT: tuple[AudioFormat, ...] = (",
        *(f"    AudioFormat({json.dumps(e)}, {rate})," for e, rate in family.audio_output.values),
        ")",
        "",
    ]


def entry_lines(entry: Entry, family: Family) -> tuple[str, ...]:
    prefix = entry.family.upper()
    return (
        "    VoiceModelSpec(",
        f"        id={json.dumps(entry.id)},",
        f"        provider={json.dumps(entry.provider)},",
        f"        voices={prefix}_VOICES,",
        f"        default_voice={json.dumps(family.default_voice)},",
        f"        audio_input={prefix}_AUDIO_INPUT,",
        f"        audio_output={prefix}_AUDIO_OUTPUT,",
        f"        reasoning_efforts={quoted(entry.efforts.values)},",
        "        sources=VoiceSources(",
        f"            model={json.dumps(entry.model_source)},",
        f"            voices={json.dumps(family.voices.source)},",
        f"            reasoning_efforts={json.dumps(entry.efforts.source)},",
        f"            audio={json.dumps(family.audio_input.source)},",
        "        ),",
        "    ),",
    )


def render(catalog: VoiceCatalog) -> str:
    lines = [
        "# Generated by scripts/generate_voice_models.py. Do not edit by hand.",
        '"""Realtime voice models; each entry\'s ``sources`` names where every value was read."""',
        "",
        "from core_ai.voice.types import AudioFormat, VoiceInfo, VoiceModelSpec, VoiceSources",
        "",
    ]
    for name, family in catalog.families.items():
        lines.extend(family_lines(name, family))
    lines.append("VOICE_MODELS: tuple[VoiceModelSpec, ...] = (")
    for entry in catalog.entries:
        lines.extend(entry_lines(entry, catalog.families[entry.family]))
    lines.extend((")", ""))
    return "\n".join(lines)


def generate(output: Path = OUTPUT) -> Path:
    catalog = collect_catalog()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(catalog))
    for provider in dict.fromkeys(entry.provider for entry in catalog.entries):
        entries = [entry for entry in catalog.entries if entry.provider == provider]
        voices = {len(catalog.families[entry.family].voices.values) for entry in entries}
        log(f"{provider}: {len(entries)} models, voices per model {sorted(voices)}")
    log(f"wrote {len(catalog.entries)} voice models to {output}")
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
    generate()


if __name__ == "__main__":
    main()
