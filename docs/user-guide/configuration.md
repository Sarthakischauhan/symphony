# Configure Symphony Code

Set up a model provider, choose defaults, and decide how the coding agent asks before acting. For workspace setup, start with the [quickstart](../getting-started/quickstart.md); the complete environment-variable list is in the [environment reference](../reference/environment.md).

## Providers and models

On first launch, Symphony can help configure a provider. In the TUI, use `/provider` to add or change credentials and `/model` to choose a model. API keys can also be set in the process environment or `.env` files. Do not commit credentials. Provider priority, subscription login, local providers, and model overrides are documented in the [environment reference](../reference/environment.md).

## Settings file

Coding-agent settings are stored in the user-wide `~/.symphony/config.json` file, or in the directory selected by `SYMPHONY_HOME`. The same settings apply across projects; workspace paths do not select a separate config file. First launch creates the file with defaults. You can edit it directly, but keep valid JSON and use the documented schema.

Configuration is loaded and maintained as a complete settings file. The TUI creates `~/.symphony/config.json` with defaults on first launch; edit that file to customize settings. For example, to require a prompt before bash commands:

```json
{
  "approvals": {
    "mode": "ask",
    "require_for_bash": true
  }
}
```

The schema is validated and rejects unrecognized or invalid settings. Keep other existing settings when editing the file.

## Updates

Before the TUI starts, an installed `symphony-code` release is compared with the latest release on PyPI. A source checkout is not replaced. When the versions differ, Symphony opens a screen with **Update now** and **Not now**. Set `updates.auto` to install the newer release without that screen:

```json
{
  "updates": {
    "enabled": true,
    "auto": false
  }
}
```

`updates.enabled: false` skips the check. `SYMPHONY_NO_UPDATE_CHECK=1` skips it for one process. An unattended command updates only when `auto` is already true; otherwise it keeps the installed version instead of prompting. After a successful update, restart `symphony`. A failed download or install leaves the current version running.

## Tool approvals

By default, approval prompts are required for `bash`, overwriting an existing file, broad patches, and web searches. The coding-agent approval add-on—not the generic harness—implements these prompts. Deny rules are checked first and block a matching tool call; otherwise allow patterns skip a prompt. `approvals.deny` applies in every mode; `approvals.allow` skips prompts in ask mode. `Always allow` changes the active agent session and is not necessarily a persistent config edit.

Patterns match the bash command or the file path. A web search is matched as `web_search:<query>`, so a bash rule such as `git *` never applies to a search. For example, `"allow": ["web_search:*"]` stops the search prompt and `"deny": ["web_search:*"]` blocks every search. Setting `approvals.require_for_web_search` to `false` also stops the prompt.

**Approvals are not a sandbox.** Bash and workspace tools execute with the current user's permissions; absolute paths are available. A bare `CoreHarness` has no approval policy. Review [Security](../../SECURITY.md) before changing defaults or running unattended.

## Unattended runs

The headless `symphony run` command requires `--unattended` to acknowledge automatic approvals. Deny rules still apply, but they are not a containment mechanism. Use a disposable environment for tasks you cannot trust. See the [CLI reference](../reference/cli.md#symphony-run-headless-coding-run).

## Context and optional integrations

The coding agent can warn about model context use and compact older conversation history. Use `/context` to inspect usage and `/compact` to request compaction. Details depend on the active model and product config.

Optional integrations have their own focused guides: [Langfuse tracing](./langfuse.md), [Jev completion checks](./jev.md), and [persistent learning](./learning.md).
