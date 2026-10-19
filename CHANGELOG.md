# Changelog

## Unreleased

- Stdio protocol 3 (`widget_fields` capability): tool events carry `call_id`,
  `parent_call_id`, output `stream`, and completion `exit_code` and `summary`;
  approvals carry `target`, `detail` and `bytes`; a derived
  `subagent_step` event follows each subagent turn. Bash reads stdout and
  stderr separately, and a non-zero exit is now a tool error. The TUI uses these
  fields and falls back to the old derivation for old sessions.

- Removed plan mode, its entry/exit tools, mode controls, saved-plan commands,
  and plan approval/build UI. There is no replacement planning gate; normal
  tool approval policies remain in effect. Legacy plan-mode sessions must not
  silently resume with write-capable tools. Planning can still be requested
  in ordinary conversation without a tool-restriction guarantee.

- Session facts are markdown in the session bundle (`<session_id>/memories/MEMORY.md`),
  not under the project's `.symphony/`. Global preferences stay in
  `~/.symphony/memories/global/`.
- Learning is on by default. A `~/.symphony/config.json` that only stores the
  old `"learning": {"enabled": false}` default is turned on and rewritten at
  launch. `--no-learning` still disables capture for that process. A learning
  block with any other key keeps the stored `enabled` value.
- `web_search` tool: searches the web through Exa's hosted endpoint with no
  account or key, and uses `EXA_API_KEY` when it is set. Each search asks for
  approval and shows the query (`approvals.require_for_web_search`); allow and
  deny rules match it as `web_search:<query>`. `tools.web_search.enabled:
  false` removes the tool. The bundled `addon-authoring`
  skill now looks up third-party API documentation with it.
- `symphony acp` is an Agent Client Protocol host (protocol version 1) for
  editors and other ACP clients: `initialize`, `session/new`,
  `session/prompt`, `session/cancel`, `session/update`, and
  `session/request_permission`, plus a `_symphony/steer` extension. It does
  not load earlier sessions, read images, or expose modes and slash commands
  yet. Approval questions now carry `tool_call_id`.
- Questions, approval state, and the cancel reason no longer live in the TUI.
  `question_asked` is a harness event emitted by the shared `HumanInteraction`
  port, so every host carries it (stdio keeps `input_requested` as an alias).
  The approval mode is state on `ApprovalAddon`; **Always allow** now also
  holds for stdio hosts, which used to be asked again on every call, and is
  announced as `config_changed`. `TextualEventSink` no longer takes
  `approvals` or has `set_approval_mode`. `run_cancelled` carries the TUI's
  reason (`user_cancel`, `quit`, `queued_send_now`).
- `CoreHarness.submit(op)` is the one inbound path for clients: `Interrupt`
  stops the active run and puts its reason on `run_cancelled`, `Answer`
  resolves a pending question, and `UserInput` adds a user message before the
  next model call. The TUI and the stdio host send these instead of cancelling
  the run task and resolving futures themselves. The stdio protocol gains a
  `steer` command and capability.
- `EventSink` separates watching from answering. `emit` now calls `deliver`
  and then every `subscribe` listener, so a second consumer can observe a run
  without wrapping the sink. Sinks override `deliver` instead of `emit`.
  `request_user_input` moved from the sink to `sink.interaction`
  (`InteractionPort`); `TextualEventSink.answer_user` moved with it. Approval
  behaviour is unchanged.
- Memory extraction requests the model's lowest advertised reasoning effort and
  an output cap of at least 8,192 tokens, so reasoning models no longer return
  empty captures. Stored `learning.max_output_tokens` values below that floor
  (the old 900 default) are raised and rewritten on launch. A provider stream
  reset now discards partial capture text. Empty or invalid extraction output
  logs a warning, shows a "memory capture" notice, and marks the job `failed`
  after three attempts instead of retrying silently every run.
- Cancel, run failures, and run limits use the same composer banner as a
  model switch. `update_banner` builds that banner from the event.
- Voice audio cleanup: leaving voice mode releases the microphone at once
  instead of when the 8 s recording cap runs out; recording waits on an event
  set from the audio callback instead of polling every 50 ms; a held realtime
  mic drops blocks in the callback without copying them or waking the loop;
  closing the TTS/realtime sockets no longer blocks the Textual loop (a new
  session waits for the old one on its own thread, and only app exit waits,
  bounded); a missing PortAudio library is reported as a voice error.
  `coding_agent/benchmarks/voice_bench.py` measures it with a fake microphone.
- Fixed voice shutdown races: cancelling pending TTS/realtime connections
  cleans up on the worker, and repeated closes do not interrupt it.
- The TUI stores its chats in `~/.symphony/tui/sessions`. Resume reads only
  that directory, so Zeron chats in `~/.symphony/sessions` never appear.
  Existing bundles tagged `client: tui` move across on first launch.
- Voice mode (`Ctrl+A` / `/voice`) keeps listening until you say **done** or
  press **Ctrl+A** again. Escape still cancels without starting a turn.
  Each transcribed utterance appears in the composer while you are still speaking.
- A voice question asks the same model call to end its answer with a
  `## Spoken summary`. Symphony dictates that section, and falls back to the
  opening of the answer if the model leaves it out. The section is removed
  from the chat and from the saved transcript. Typed turns stay silent.
- Voice activity now keeps the composer visible and blinks its rounded border
  between light and dark purple every 0.5 seconds instead of showing a sweep bar.
- Optional TUI voice input (`Ctrl+A` / `/voice`) records one utterance with
  xAI transcription and streams the coding agent's own text through a separate
  TTS websocket. Voice turns are explicitly scoped; typed turns and subagents
  stay silent. Added cancellation/startup/playback regressions and a
  [voice call/protocol diagram](docs/developer-guide/voice-mode.md).

- Replaced legacy Markdown memory and idle reflection with durable per-turn
  capture jobs, candidate observation inboxes, deduplicated workspace/global
  topics, and SQLite FTS5/BM25 recall. Automatic pre-model retrieval shares
  bounded recent-context/preference injection across parent and child turns.
  Added `memory_search`, `memory_get`, and Session/Global memory UI tabs; queued jobs survive
  shutdown. Old memory files are ignored rather than silently migrated.

- Sessions now own `~/.symphony/sessions/<session_id>/` bundles containing the
  append-only transcript, versioned metadata, checkpoints, content-addressed
  images, compaction history, memory operations and snapshots, session learning
  provenance, stdio state, and detached-run files. Legacy flat transcripts remain
  readable and migrate on access. `/session` inspects these artifacts in the
  TUI and stdio; `/learning` also displays workspace lessons.

- Sessions a live Symphony process still owns are recorded under
  `~/.symphony/active` and left out of `symphony --resume`. The picker only
  lists closed conversations. `/dashboard` opens a subagent-style list of
  those live agents with CPU, memory, and disk, sampled per OS.
- `symphony-browser` (workspace package `browser_agent`): a browser-use agent
  whose loop is `CoreHarness.run`. The goal is the user message. The chat
  model calls `observe_page`, `click`, `type_text`, `press_enter`,
  `select_option`, `scroll_down`, `scroll_up`, and `wait`; its final message,
  with no tool call, is `output_text`. Jev is not the policy: an evaluation
  model cannot emit a tool call. `--max-steps` is the harness turn cap.
  `symphony-browser "query"` starts from a DuckDuckGo HTML search
  (`https://html.duckduckgo.com/html/`), not Google, whose bot interstitial
  blocks a fresh Playwright Chromium. The command uses the configured chat
  provider and exits when none is configured.
- Headless `symphony bench` CLI plus `symphony-bench:latest` Docker image and
  a thin Harbor adapter (`bench.agent:SymphonyAgent`). Writes `workspace.patch`
  and `result.json`; Harbor's grader owns pass/fail.
- Mid-run control-plane events (after the user message, before the final
  output) are tagged `collected: true` in the JSONL journal when a run
  finishes. The TUI honours the sticky flag on resume by folding that work
  into the completed-run collection instead of replaying live cards.
- Session updates such as model, effort, provider, and compaction now appear
  in a transient composer overlay with a `ctrl+q` quit hint, matching the
  interrupt confirmation card instead of a transcript notice.
- The completed-run collection in the TUI is now an unbracketed past-tense
  Claude-style verb plus duration, for example `Stargazed for 2m 2s`, instead
  of `[ Cooked … ]`. Live churning status uses matching spinner words such as
  `Stargazing` and `Noodling`.
- `symphony-core` registers OpenRouter (`OPENROUTER_API_KEY`) and Vercel AI
  Gateway (`AI_GATEWAY_API_KEY`) as OpenAI-compatible Chat Completions
  providers. Model slugs like `openai/gpt-4o` are discovered from `/models`
  at registry build. Vercel evaluation models such as `typesafe-ai/jev` use
  the Gateway protocol (`POST /v4/ai/evaluation-model`), not the OpenAI-compatible
  `/v1` base. Chat completions stay on `/v1/chat/completions`.
- Optional `LangfuseAddon` on `symphony-code` records the conversation sent
  each model turn, plus tools and compaction, when `LANGFUSE_PUBLIC_KEY` and
  `LANGFUSE_SECRET_KEY` are set. `/langfuse` saves keys and installs the
  optional SDK if it is missing. In the workspace, install the optional SDK with `uv sync --package symphony-code --extra langfuse`. Disable with `"langfuse": {"enabled": false}`. Observation
  input/output (run task, turn text and tool calls, tool arguments, and final
  `output_text`) is redacted before it leaves the process. Root spans no longer
  pass `session_id` into Langfuse v4 `start_observation` (that TypeError was
  swallowed and produced zero traces).
- Optional Jev critic mode on `symphony-code` (`--jev` / `/jev`). Findings
  plus a per-action in-thread critic note: the chat model is unchanged, scores
  do not rewrite the task, honour / auto-follow-up stays
  off, and provider errors fail open. Off by default.
- `/provider` and first-run onboarding can sign in with a ChatGPT (Codex),
  Claude (`claude setup-token` or browser code), or xAI (device code)
  subscription. Tokens live in `~/.symphony/oauth/` and are used when no
  API key is set. API keys still work. ChatGPT OAuth calls the Codex
  backend (`store: false`, typed Responses input). xAI OAuth calls
  `https://cli-chat-proxy.grok.com/v1`; `XAI_API_KEY` still uses `api.x.ai`.

## 0.1.0 — first public release

This section records historical release behavior, including features since removed.

The 0.1.0 project release included distributions named `symphony-core`,
`symphony-harness`, and `symphony-code`. This history does not guarantee that
the packages are currently installable from PyPI; check the current
[installation guide](docs/getting-started/installation.md). `core-server` was
kept in the workspace and was not part of that release.

### symphony-core

- OpenAI (Responses and Chat Completions, plus `gpt-image-*`), Anthropic
  Messages, Gemini `streamGenerateContent`, Grok Chat Completions.
- Shared `Message` / `StreamEvent` contract, including `reasoning_delta` and
  retry on 429, SSL MAC, 5xx, and connection errors.
- Checked-in model catalog from models.dev. Install and build do not refresh it.

### symphony-harness

- Multi-turn tool loop with run caps (turns, tools, runtime, tokens).
- Event sink (`EventSink.emit`) plus compaction. Persistence and spawn
  are add-ons. Cancel a run by cancelling the `asyncio.Task`.
- Tools run unless a `before_tool` add-on denies them. `symphony-code`
  mounts `ApprovalAddon`; the harness does not authorize tools.
- Subagents, parallel tool calls, keep/drop compaction planner.

### symphony-code

- Workspace tools: `read_file`, `write_file`, `patch`, `search`, `bash`,
  `generate_image`, `ask_user`, `spawn_agent`.
- Textual TUI, plan mode, JSONL sessions under `.sessions/`.
- Approval policy lives in `coding_agent.addons.approvals`; the TUI only renders the
  question. Children still run without per-tool prompts (see `SECURITY.md`).
- Post-run learning into `.symphony/learning/lessons.jsonl`.

### Known limits in 0.1.0

- Compaction still rewrites the stored conversation. The user-facing TUI hides
  compacted context; a later change will keep the full log and project a
  compact view to the model.
- No skill/plugin loader. Add-ons are attached in Python.
- Learning is a bounded lesson log, not durable retrieval memory.
- `core-server` has no authentication and does not answer `ask_user`.
- File tools are not jailed to the launch directory. Relative paths start
  there; absolute and `~` paths are allowed. `bash` is not a sandbox.
