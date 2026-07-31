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

`CodingAgent` does **not** auto-accumulate history across separate `run()` calls. That is intentional for now: the harness owns in-run state; multi-run sessions are the caller's job.

```python
result = await agent.run("Create hello.txt")
# Continue with prior turns (drop the harness-injected system message):
result = await agent.run(
    "Now read it back",
    conversation=result.messages[1:],
)
```

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
- `tui/control_plane.py` — CP → UI message bridge
- `tui/__main__.py` — CLI entry
