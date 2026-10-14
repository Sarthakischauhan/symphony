# Workspace tools

Symphony Code gives the model a set of tools for working in the selected workspace. Tools are capabilities: if one can read files or execute commands, the agent can use that capability as part of a task. Review actions and results; this is not a sandbox.

## Available tools

| Tool | Use |
| --- | --- |
| `read_file` | Read a workspace file |
| `write_file` | Create or replace a file |
| `patch` | Apply a targeted text change |
| `search` | Find files and matching text |
| `web_search` | Look up documentation and other pages on the web |
| `bash` | Run a shell command |
| `generate_image` | Create an image asset |
| `ask_user` | Request human input when the interface supports it |
| `spawn_agent` | Delegate a bounded task to a child agent |

The exact tool schemas and options are defined in the coding-agent source and may change. The model generally chooses tools based on the task; it does not need users to specify an API call.

## Paths and shell commands

Relative paths use the chosen workspace as their base, but absolute paths and `~` paths are allowed. Bash runs with the permissions of the Symphony process. The workspace setting is **not a path jail**. Do not ask Symphony to inspect secrets or run a command you would not run yourself.

Interactive approval prompts can ask before selected operations. A harness used outside Symphony Code does not automatically provide those prompts. Read the [security policy](../../SECURITY.md) before using unattended runs or untrusted workspaces.

## Web search

`web_search` needs no account or API key. It sends the query to [Exa](https://exa.ai)'s hosted search endpoint and returns titles, URLs, and text excerpts from the top results.

- **The query leaves your machine.** Symphony asks before each search and shows the exact query. See [tool approvals](./configuration.md#tool-approvals) to change that.
- **Results are untrusted web content.** They go into the model's context like any other tool output, so a page can try to steer the model. Review what the agent does after a search.
- **Keyless use is rate limited.** When the limit is hit the tool returns an error and the agent can retry. Set `EXA_API_KEY` in your environment or `.env` to use your own Exa account instead; usage is then billed by Exa to that account.
- **Turn it off** with `"tools": {"web_search": {"enabled": false}}` in `~/.symphony/config.json`. The tool is then not offered to the model at all.

The tool searches only. It does not fetch arbitrary URLs.

## Add a tool to your agent

For a custom harness application, wrap an explicit Python callable with `core_harness.Tool` and register it on the harness. See the [harness guide](../packages/symphony-harness.md) and [extension guide](../developer-guide/extending.md).
