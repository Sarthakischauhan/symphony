# Voice mode: capture, agent execution, and speech

Voice mode is an optional Symphony TUI feature, entered with **Ctrl+A** or
`/voice`. It does not change the coding model. The implementation currently
uses separate transcription, realtime, and streaming-TTS connections; it is
not a single end-to-end speech-to-code websocket.

## Call and protocol map

```mermaid
sequenceDiagram
    actor User
    participant UI as Textual TUI / voice_mode.py
    participant Mic as sounddevice / PortAudio
    participant STT as xAI HTTPS /v1/stt
    participant Addon as VoiceAddon
    participant RT as xAI WSS /v1/realtime
    participant Agent as CodingAgent / CoreHarness
    participant Model as Configured chat provider
    participant TTS as xAI WSS /v1/tts
    participant Player as Local audio player

    User->>UI: Ctrl+A or /voice
    UI->>UI: Guard busy/offline; blink composer border every 0.5s
    UI->>Mic: Worker thread: record 8s mono PCM16, 16 kHz
    Mic-->>UI: WAV bytes
    UI->>STT: POST multipart: model, language=en, file
    Note over UI,STT: Bearer XAI_API_KEY, otherwise stored Grok OAuth token
    STT-->>UI: JSON transcript
    alt Cancelled capture, error, or empty transcript
        UI->>UI: Ignore stale capture or show notice; restore composer
    else Transcript accepted
        UI->>Addon: ensure_voice_addon(); open(); arm one voice turn
        Addon->>RT: WebSocket upgrade, model=grok-voice-think-fast-2.0
        Addon->>RT: session.update (eve, PCM16 24 kHz, server_vad)
        Note over Addon,RT: Realtime mic stream is separate from STT; not the coding prompt path
        UI->>Agent: QueuedTurn through normal _start_turn
        Agent->>Addon: before_run: hold realtime mic
        Agent->>Model: Normal provider request; chat model unchanged
        loop Assistant text and tool execution
            Model-->>Agent: Assistant text deltas / tool calls
            Agent-->>UI: Typed control-plane text_delta events
            UI->>Addon: feed_voice(cumulative assistant text)
            Addon->>TTS: WebSocket upgrade on first text (eve, en, mp3)
            Addon->>TTS: text.delta for first clause, then completed sentences
            TTS-->>Addon: Binary MP3 or JSON audio.delta (base64)
            Addon->>Player: MP3 bytes to ffplay/mpv stdin
            Note over Addon,Player: Without a streaming player, buffer and use local MP3 playback
        end
        Agent->>Addon: after_run(result.output_text)
        Addon->>TTS: Flush remaining text; text.done
        TTS-->>Addon: audio.done
        Addon->>Player: Drain playback; restore normal composer border
        Addon->>RT: Close realtime socket
        UI->>UI: Stop border blink after speech
    end
```

### External calls

| Purpose | Endpoint / transport | Request and response |
| --- | --- | --- |
| Transcription | `POST https://api.x.ai/v1/stt`, HTTPS multipart | `model=grok-voice-transcribe-2.0`, `language=en`, WAV `file`; JSON `text`. Model fields precede file. 30s timeout. |
| Realtime audio | `wss://api.x.ai/v1/realtime?model=grok-voice-think-fast-2.0`, WebSocket JSON | `session.update`, base64 `input_audio_buffer.append`; PCM audio response deltas. This connection does **not** submit coding turns. |
| Spoken agent output | `wss://api.x.ai/v1/tts`, WebSocket JSON / binary | Query: `voice=eve`, `language=en`, `codec=mp3`, `optimize_streaming_latency=1`. Send `text.delta` and `text.done`; receive binary MP3 or `audio.delta`, then `audio.done`. |
| MP3 helper (not normal streamed output) | `POST https://api.x.ai/v1/tts`, HTTPS JSON | `text`, `voice_id=eve`, `language=en`; MP3 response. Used by the standalone synthesis helper, not `VoiceAddon.feed`. |
| Coding model | Existing configured provider protocol | Unchanged: provider-specific streaming request, tools, approvals, persistence, and final response. |

All xAI audio connections use a Bearer token: `XAI_API_KEY` takes precedence;
otherwise `grok_voice_credentials()` uses the stored Grok device-login token
and its extra headers. They target `api.x.ai`, not the CLI chat proxy. Actual
account access and API compatibility must be checked with a live smoke test;
unit tests mock the provider and do not prove entitlement.

## When does output get spoken?

`EventPresenter._on_text_delta` forwards the accumulated assistant text to
`TurnSurface.feed_voice` and then `VoiceAddon.feed`. On a voice-originated run,
the first nonempty clause is submitted immediately; later text waits for
`.`, `?`, `!`, or a newline. `after_run` flushes the remaining tail and sends
`text.done`. There is no canned "working on it" sentence. Tool output and
reasoning deltas are not fed to this path.

Socket setup, TTS generation, and the local player still add latency. With
`ffplay` or `mpv`, MP3 bytes are written as they arrive; with only `afplay`,
audio must be buffered before file playback. This is not a guarantee that
sound starts at the same instant as the first visible token.

The voice addon stays registered but is armed for one voice turn only. Later
typed turns and child harnesses stay silent. Cancellation/quit closes voice
resources; failed runs must also clear the voice indicator. The composer and approval
choices remain visible and actionable throughout voice activity. Its existing
rounded border alternates light purple (`#D7C4FB`) and dark purple (`#A371F7`)
every 0.5 seconds; removing the voice classes restores the theme/focus border.
There is no separate voice bar and no composer hide/show transition.

## Owners and limits

- `tui/composer/voice.py`: credentials, fixed-duration WAV capture, STT client,
  border-color constants, and standalone HTTP TTS/playback helpers.
- `tui/composer/voice_mode.py`: user entry, capture worker, stale-result guard,
  transcript handoff, addon activation, and UI recovery.
- `addons/voice/addon.py`: per-run opt-in, streamed text forwarding, tail flush,
  and resource ownership.
- `addons/voice/speak.py` and `stream.py`: streaming-TTS and realtime socket
  workers, respectively, plus local audio playback.

Capture is fixed at eight seconds, not silence-ended or push-to-talk.
Cancelling invalidates the result; it does not instantly interrupt the
underlying fixed-duration recorder. Audio is sent to xAI, and assistant text
sent to TTS can contain workspace information. Input/output language is
currently hardcoded to English. `sounddevice` is optional and first use tries
to install it in the running interpreter; PortAudio/device availability and
a local player are also required. The realtime connection duplicates an
otherwise REST-STT-plus-TTS design and is a future simplification candidate;
it should not be described as a continuous coding conversation.

## Verification

Run `uv run pytest coding_agent/tests/test_voice*.py` for mocked capture,
activation, socket lifecycle, and playback regressions. Run
`uv run python coding_agent/benchmarks/tui_render_bench.py --voice` for border-blink
render cost. Tests never require microphone access or provider keys. A manual
smoke test is still needed for xAI audio API compatibility, permissions,
first-sound latency, and playback on the target OS.
