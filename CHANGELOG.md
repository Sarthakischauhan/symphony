# Changelog

## Unreleased

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
  optional SDK if it is missing. You can still install `symphony-code[langfuse]`
  yourself. Disable with `"langfuse": {"enabled": false}`. Observation
  input/output (run task, turn text and tool calls, tool arguments, and final
  `output_text`) is redacted before it leaves the process. Root spans no longer
  pass `session_id` into Langfuse v4 `start_observation` (that TypeError was
  swallowed and produced zero traces).
- Optional Jev critic mode on `symphony-code` (`--jev` / `/jev`). Findings
  plus a per-action in-thread critic note: the chat model is unchanged, scores
  do not rewrite the plan or enter plan mode, honour / auto-follow-up stays
  off, and provider errors fail open. Off by default.
- `/provider` and first-run onboarding can sign in with a ChatGPT (Codex),
  Claude (`claude setup-token` or browser code), or xAI (device code)
  subscription. Tokens live in `~/.symphony/oauth/` and are used when no
  API key is set. API keys still work. ChatGPT OAuth calls the Codex
  backend (`store: false`, typed Responses input). xAI OAuth calls
  `https://cli-chat-proxy.grok.com/v1`; `XAI_API_KEY` still uses `api.x.ai`.

## 0.1.0 — first public release

Three packages on PyPI: `symphony-core`, `symphony-harness`, `symphony-code`.
`core-server` stays in the workspace and is not published.

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
- Approval policy lives in `coding_agent.approvals`; the TUI only renders the
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
