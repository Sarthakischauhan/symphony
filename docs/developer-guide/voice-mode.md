# Voice mode: capture, agent execution, and speech

Voice mode is an optional Symphony TUI feature, entered with **Ctrl+A** or
`/voice`. It does not change the coding model. Listening is one realtime
socket: mic audio goes up as the user speaks, transcript deltas come back
immediately, and the utterance is committed after a 3 second pause or Enter.
Listening uses one speech-to-speech socket, `grok-voice-think-fast-2.0`.
It hangs up when the acknowledgement finishes, so the coding run is not
billed as voice time. The spoken summary opens its own short connection on
the same model and hangs up when that line finishes. The written answer
stays in the chat and is not dictated. There is no TTS or STT connection.

## Call and protocol map

```mermaid
sequenceDiagram
    actor User
    participant UI as Textual TUI
    participant Mic as Microphone
    participant STT as xAI STT
    participant Addon as VoiceAddon
    participant RT as xAI Realtime
    participant Agent as CodingAgent
    participant Model as Chat provider
    participant Player as Local player

    User->>UI: Ctrl+A or /voice
    UI->>UI: Guard busy or offline, blink composer border
    UI->>Addon: Open the realtime socket and arm one voice turn
    Addon->>RT: Connect grok-voice-think-fast-2.0
    Addon->>RT: session.update, voice eve, PCM 24 kHz, no server VAD
    loop While the user speaks
        UI->>RT: input_audio_buffer.append (one PCM block)
        RT-->>UI: input_audio_transcription.delta, shown in the composer
        RT-->>Player: Brief acknowledgement audio only
    end
    alt Escape
        UI->>UI: Drop the transcript, restore composer
    else 3 second pause or Enter
        UI->>RT: input_audio_buffer.commit, then response.create for one acknowledgement
        UI->>UI: Submit the transcript as the coding turn
        Note over Addon,RT: Realtime mic is not the coding prompt
        UI->>UI: Clear composer and queue the voice turn
        UI->>Agent: Start turn with reply_aloud
        Agent->>Addon: before_run holds the realtime mic
        Note over Agent,Model: Request-only note asks for a Spoken summary. System prompt stays the same
        loop Tools and the written answer
            Agent->>Model: Unchanged chat provider and tools
            Model-->>Agent: Text deltas and tool calls
            Agent-->>UI: Transcript events only
            Note over UI,Addon: Deltas, tools, and reasoning are not spoken
        end
        Agent->>Agent: Copy reply_aloud onto the result, then clear it
        Agent->>Addon: after_run
        Addon->>RT: Say only the Spoken summary, verbatim
        RT-->>Player: PCM of that summary, not the written answer
        Addon->>Player: Play with ffplay, mpv, or afplay
        UI->>UI: Stop the border blink after speech
    end
```

### External calls

| Purpose | Endpoint / transport | Request and response |
| --- | --- | --- |
| Transcription | `POST https://api.x.ai/v1/stt`, HTTPS multipart | `model=grok-voice-transcribe-2.0`, `language=en`, WAV `file`; JSON `text`. Model fields precede file. 30s timeout. |
| Realtime audio | `wss://api.x.ai/v1/realtime?model=grok-voice-think-fast-2.0`, WebSocket JSON | `session.update` (no server VAD), base64 `input_audio_buffer.append`, then `input_audio_buffer.commit` and `response.create` after 3 s of quiet or Enter. Transcript deltas update the composer. The created response is one spoken acknowledgement. |
| Spoken summary | `wss://api.x.ai/v1/tts`, WebSocket opened after the run | `voice=eve`, `language=en`, `codec=mp3`. One `text.delta` of the summary, then `text.done`. MP3 is played as it arrives; the socket stays up until `audio.done`. Not the realtime socket: that one closes on the acknowledgement and was cutting this line off. |
| Coding model | Existing configured provider protocol | Unchanged: provider-specific streaming request, tools, approvals, persistence, and final response. |

All xAI audio connections use a Bearer token: `XAI_API_KEY` takes precedence;
otherwise `grok_voice_credentials()` uses the stored Grok device-login token
and its extra headers. They target `api.x.ai`, not the CLI chat proxy. Actual
account access and API compatibility must be checked with a live smoke test;
unit tests mock the provider and do not prove entitlement.

## When does output get spoken?

A voice question sets `CoreHarness.reply_aloud` for the run that is about to
start. `run_session` copies that flag onto `HarnessResult.reply_aloud` and
clears it, so the next typed turn stays silent. For that run only, the per-turn request context asks the model to finish its
normal answer with a `## Spoken summary` section. The system prompt is not
changed, so the provider prefix cache still matches. The note is not persisted
and does not add a model call.
`VoiceAddon.after_run` speaks that section (fences stripped, length capped).
If the model omits it, nothing is spoken. The whole answer is never dictated. The
section is stripped before the answer is shown or saved, including while the
heading is still streaming, so the chat never displays it. Streamed deltas,
tool output, and reasoning are not dictated. There is no canned
"working on it" sentence.

The acknowledgement is PCM from the realtime socket, which closes when that
response finishes so it is not held through the coding run. The summary is
MP3 from a separate TTS socket opened after the run. That socket stays open
until `audio.done`, which is what the realtime socket would not do: its
`response.done` arrived with the first audio and playback never got the line.
Streaming MP3 starts as frames arrive, so the first sound is still not the
first visible token.

The voice addon stays registered but is armed for one voice turn only. Later
typed turns and child harnesses stay silent. Cancellation/quit closes voice
resources; failed runs must also clear the voice indicator. The composer and approval
choices remain visible and actionable throughout voice activity. Its existing
rounded border alternates light purple (`#D7C4FB`) and dark purple (`#A371F7`)
every 0.5 seconds; removing the voice classes restores the theme/focus border.
There is no separate voice bar and no composer hide/show transition.

## Owners and limits

- `tui/composer/voice.py`: credentials, the test-only WAV recorder and REST
  STT client, border colors, and the spoken-summary splitter.
- `tui/composer/voice_mode.py`: user entry, live transcript, commit on pause
  or Enter, and UI recovery.
- `addons/voice/addon.py`: per-run opt-in. Speaks the summary through TTS
  after the run, not on the realtime socket.
- `addons/voice/stream.py`: the listen socket, microphone, and acknowledgement
  playback. `speak.py` is the TTS socket used for the summary.

One listen is one utterance. Audio is appended while the user speaks, and the
composer shows transcript deltas as they arrive, on the same socket. The turn
starts when the speaker has been quiet for 3 seconds, or when they press
Enter (Ctrl+A does the same). Escape cancels without submitting. The
realtime model speaks a brief acknowledgement on commit, then the socket
closes. After the run, TTS speaks the spoken-summary section and nothing
else. That spoken line is not the chat
answer. A voice utterance while a turn is already running is queued in the
composer and sent when the current run finishes. Audio is sent to xAI, and
the summary can contain workspace information. Input/output
language is currently hardcoded to English. `sounddevice` is optional and
first use tries to install it in the running interpreter; PortAudio/device
availability and a local player are also required. The older local WAV
recorder and REST STT client remain for tests and are not on the live path.

## Verification

Run `uv run pytest coding_agent/tests/test_voice*.py` for mocked capture,
activation, socket lifecycle, and playback regressions. Run
`uv run python coding_agent/benchmarks/tui_render_bench.py --voice` for border-blink
render cost. Tests never require microphone access or provider keys. A manual
smoke test is still needed for xAI audio API compatibility, permissions,
first-sound latency, and playback on the target OS.
