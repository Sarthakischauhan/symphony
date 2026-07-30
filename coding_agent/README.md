## coding_agent

Minimal coding agent product on top of `core_harness`.

### Surface

- `CodingAgent` — wires workspace tools into `CoreHarness`
- tools: `read`, `write`, `bash` (scoped to a workspace directory)
- **TUI** — minimal Textual chat shell (`coding_agent.tui`)

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

### TUI

Requires `OPENAI_API_KEY` (optional `OPENAI_BASE_URL`, `OPENAI_MODEL`, `CODING_AGENT_WORKSPACE`):

```bash
export OPENAI_API_KEY=...
uv run coding-agent-tui --workspace ./.workspace
# or
uv run python -m coding_agent.tui --workspace ./.workspace
```

Scaffold layout:

- transcript log + status line + input
- control-plane events for tool start/complete
- quit with `q` / `Ctrl+C`

### Layout

- `agent.py` — `CodingAgent`
- `tools.py` — workspace-scoped read / write / bash
- `prompts.py` — default system prompt
- `tui/app.py` — Textual app
- `tui/control_plane.py` — CP → UI message bridge
- `tui/__main__.py` — CLI entry
