# Workspace tools

Symphony Code gives the model a set of tools for working in the selected workspace. Tools are capabilities: if one can read files or execute commands, the agent can use that capability as part of a task. Review actions and results; this is not a sandbox.

## Available tools

| Tool | Use |
| --- | --- |
| `read_file` | Read a workspace file |
| `write_file` | Create or replace a file |
| `patch` | Apply a targeted text change |
| `search` | Find files and matching text |
| `bash` | Run a shell command |
| `generate_image` | Create an image asset |
| `ask_user` | Request human input when the interface supports it |
| `spawn_agent` | Delegate a bounded task to a child agent |

The exact tool schemas and options are defined in the coding-agent source and may change. The model generally chooses tools based on the task; it does not need users to specify an API call.

## Paths and shell commands

Relative paths use the chosen workspace as their base, but absolute paths and `~` paths are allowed. Bash runs with the permissions of the Symphony process. The workspace setting is **not a path jail**. Do not ask Symphony to inspect secrets or run a command you would not run yourself.

Interactive approval prompts can ask before selected operations. A harness used outside Symphony Code does not automatically provide those prompts. Read the [security policy](../../SECURITY.md) before using unattended runs or untrusted workspaces.

## Add a tool to your agent

For a custom harness application, wrap an explicit Python callable with `core_harness.Tool` and register it on the harness. See the [harness guide](../packages/symphony-harness.md) and [extension guide](../developer-guide/extending.md).
