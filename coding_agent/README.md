## coding_agent

Coding agent product on top of `core_harness`.

### Run it

1. Set `OPENAI_API_KEY`.
2. Optionally set `OPENAI_BASE_URL`, `OPENAI_MODEL`, or `CODING_AGENT_WORKSPACE`.
3. From the repo root, launch the TUI with:

```bash
uv run --package coding-agent coding-agent-tui
# or
uv run --package coding-agent python -m coding_agent.tui
```

The default workspace is `.workspace`. To use a different workspace:

```bash
uv run --package coding-agent coding-agent-tui --workspace /tmp/coding-agent-workspace
```

### Surface

- `CodingAgent` — wires workspace tools into `CoreHarness`
- tools (one module each): `read_file`, `write_file`, `bash`, `grep`
- `build_tools(workspace)` — register all tools for a workspace root

```python
from core_ai import ModelRegistry, OpenAIProvider
from coding_agent import CodingAgent

registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

agent = CodingAgent(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    workspace="./.workspace",
)

result = await agent.run("Create hello.txt with hi, then read it back.")
print(result.output_text)
```

If you only want the CLI/TUI and not the Python API, `uv run --package coding-agent coding-agent-tui` is the fastest path.

### Conversation / memory

`CoreHarness` keeps the full message list **inside a single** `run()` (system → user → tool turns → final assistant).

Across runs, `CodingAgent` defaults to `SqlitePersistence` under
`<workspace>/.symphony/sessions.sqlite3` and a stable `session_id`. When you omit
`conversation=`, the harness reloads prior messages from that store.

```python
from coding_agent import CodingAgent, SqlitePersistence

agent = CodingAgent(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    workspace="./.workspace",
    persistence=SqlitePersistence("./.workspace/.symphony/sessions.sqlite3"),
    session_id="my-session",
)

result = await agent.run("Create hello.txt")
result = await agent.run("Now read it back")  # resumes via SQLite
```

You can still pass an explicit `conversation=` list to override the loaded history.

### Tool pattern

Each tool lives in its own file under `coding_agent/tools/`:

1. Subclass `WorkspaceTool`
2. Define a pydantic `ToolArgsModel` with `Field(..., description=...)`
3. Set `name`, `description`, and `args_model`
4. Implement `run(...)` with typed parameters
5. Register the class in `TOOL_CLASSES` inside `tools/__init__.py`

Shared path safety, JSON Schema export, and argument validation live in `tools/base.py`.

### Layout

- `agent.py` — `CodingAgent`
- `tools/base.py` — `WorkspaceTool` + `ToolArgsModel`
- `tools/read_file.py` — `ReadFileTool`
- `tools/write_file.py` — `WriteFileTool`
- `tools/bash.py` — `BashTool`
- `tools/grep.py` — `GrepTool`
- `prompts.py` — default system prompt
- `tui/app.py` — Textual app
- `tui/control_plane.py` — thin harness `ControlPlane` → Textual sink
- `tui/events.py` — present every harness event in the UI
- `tui/state.py` — live phase / tokens / context_left
- `tui/__main__.py` — CLI entry
- `persistence/sqlite.py` — SQLite conversation + checkpoint store

The TUI does **not** invent a second control plane. `TextualControlPlane` implements the core_harness `ControlPlane` protocol so the same emit stream drives the UI (thinking/turns, streamed `text_delta`, tools, usage, context).
