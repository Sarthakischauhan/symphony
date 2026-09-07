# symphony-code

The coding agent. Workspace tools + a Textual TUI, sitting on
`symphony-harness`. Import it as `coding_agent`.

```sh
uv add symphony-code
uv run --package symphony-code symphony --workspace .
```

If no API key is set, the TUI asks which provider to use and saves the key to
`~/.symphony/.env`. `/provider` adds another later.

`symphony`, `symphony-code`, and `coding-agent-tui` are the same command.

<video src="../docs/demo.mp4" controls muted loop playsinline poster="../docs/demo.png" width="800">
  <a href="../docs/demo.mp4">Demo: create hello.py, write a test, run pytest — 1 passed</a>
</video>

Ask something you can verify on disk:

```text
Create hello.py with a greet() function and a test, then run it.
```

You should see `Write` / `Bash` rows in the transcript, then `hello.py` on
disk. `Esc` cancels. `/` is the command menu. `Tab` toggles **build** / **plan**.

## Library

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()
agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".",
)
print((await agent.run("Fix the failing test")).output_text)
```

## Docs

| | |
| --- | --- |
| [symphony-code](../docs/packages/symphony-code.md) | Watch a run, then install |
| [TUI](../docs/user-guide/tui.md) | Keybindings, plan mode, images |
| [Tools](../docs/user-guide/tools.md) | `read_file`, `write_file`, `patch`, `search`, `bash`, `spawn_agent` |
| [Configuration](../docs/user-guide/configuration.md) | `.symphony/config.json`, approvals |
| [Slash commands](../docs/reference/slash-commands.md) | `/model`, `/plan`, `/resume`, … |

The agent asks before bash, overwrite, or a broad patch. Approval rules live
in `coding_agent.approvals`; the TUI only renders the question. Sessions
persist in `.symphony/sessions/<session_id>.jsonl` (`--resume`).

Subagents run in the background by default and return results automatically to
the parent runtime. Press **Ctrl+G** to inspect their saved or live transcripts,
with the same tool/thought compaction as the parent. **Esc** returns to the parent;
**Ctrl+X** in the child view cancels that child. Child histories persist separately
in their own session files; closing the app stops active children.
