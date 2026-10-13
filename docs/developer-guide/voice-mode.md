# Voice mode

Voice mode lets a user dictate a task to Symphony Code and hear a short spoken summary when the coding run finishes. It is an optional terminal-interface feature, not a different agent or model loop. Enter it with `Ctrl+A` or `/voice`.

## Interaction flow

1. `Ctrl+A` or `/voice` opens the voice interface. The TUI captures audio and displays transcription in the composer as clips are recognized.
2. A quiet interval commits each voice clip; voice mode stays open and collects subsequent clips. Say **“done”** or press `Ctrl+A` to submit the collected text. Escape cancels it.
3. The audio service may acknowledge a committed clip. Input/transcription and speech are sent through separate voice services.
4. When voice capture finishes, the recognized text is submitted as an ordinary coding-agent turn using the configured chat provider and existing tools/approval behavior.
5. After the run, a separate speech connection plays a short `Spoken summary` if the model produced one. The full written answer remains in the transcript; tool activity, reasoning, and the full reply are not dictated.

The voice input and spoken summary are sent to xAI services. Do not dictate secrets or assume spoken output is private. Language support and audio availability depend on the current implementation and host audio setup. Microphone and playback permissions are controlled by the operating system.

## Requirements and setup

Voice mode requires the coding agent's audio dependencies, an available input device, local playback support, and xAI voice credentials. API-key auth uses `XAI_API_KEY`; supported Grok subscription credentials can be used when available. If the optional voice dependency is missing, `/voice` prints the source-workspace command to install its `voice` extra. Check the [environment reference](../reference/environment.md) and `/voice` availability in the TUI. Voice is optional; ordinary typed interaction does not require it.

## Implementation boundary

The TUI owns microphone capture and composer state. The voice add-on owns connection lifecycle and spoken summaries. Voice does not replace the configured chat provider, add an approval bypass, or speak subagent activity. For extension boundaries, see [Architecture](./architecture.md) and [Extending the harness](./extending.md).

Tests mock audio and network APIs; passing them does not establish live account entitlement or provider availability. A manual smoke test is required for microphone permissions, xAI API access, and playback on a target system.
