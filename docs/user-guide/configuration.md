# Configure Symphony Code

## Agent profiles

Select a named profile with `symphony --profile reviewer` or `symphony run --unattended --profile reviewer "Review the changes"`. Profiles live at `.symphony/agents/NAME.yaml` (or `.yml`) in the workspace, or under `~/.symphony/agents/`; a project profile takes precedence. `SYMPHONY_HOME` overrides the user directory. Names contain only letters, numbers, `_`, and `-`.

```yaml
name: reviewer
model: anthropic:claude-sonnet-4-6
instructions: |
  Review changes for correctness and missing tests.
tools:
  - read_file
  - search
```

To use a profile for a delegated task, ask the main agent to use that profile when spawning a child. Child profiles may only select tools already available to the parent, and cannot change approval rules. The configured model remains subject to the existing cheaper-child policy. For ChatGPT subscriptions, Symphony cannot verify that an automatically selected cheaper catalog model is supported, so delegation requires an explicit supported model in the child profile rather than silently using a more expensive fallback. While a child is running, `Ctrl+G` opens its transcript, where you can send guidance; a completed child can receive a follow-up with its earlier context. The parent can use `message_agent` to message a child or list its children with an empty child ID. Children remain available for reuse during the current process only.

All fields are optional; if supplied, `name` must match the filename. `model` is a default, overridden by `--model`. `instructions` supplement the base prompt. `tools` is an exact allowlist of registered tools, including addon tools, `spawn_agent`, and `message_agent`; omit it to keep the normal tool set. Unknown tools and fields are errors. An allowlist is not a sandbox: tools such as `bash` can perform arbitrary actions with your permissions. Profiles do not change approvals or child-agent security policy. Profiles are selected explicitly and are not saved with a session; select the same profile when resuming. `--resume --continue` does not accept a profile.


Set up a model provider, choose defaults, and decide how the coding agent asks before acting. For workspace setup, start with the [quickstart](../getting-started/quickstart.md); the complete environment-variable list is in the [environment reference](../reference/environment.md).

## Providers and models

On first launch, Symphony can help configure a provider. In the TUI, use `/login` to add or change credentials and `/model` to choose a model. API keys can also be set in the process environment or `.env` files. Do not commit credentials. Provider priority, subscription login, local providers, and model overrides are documented in the [environment reference](../reference/environment.md).

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

Known settings are validated. Unrecognized settings are ignored when the file is loaded and removed the next time Symphony refreshes it, including settings added by a newer version. Keep a backup if you switch between versions and want to preserve those settings.

## Updates

Before the TUI starts, an installed `symphony-code` release is compared with the latest release on PyPI. Only a uv tool install of the PyPI release (what `install.sh` or `uv tool install symphony-code` sets up, as `uv tool list` reports it) is ever upgraded, with `uv tool install --upgrade`. A run from a source checkout, a local `file://` install (editable or not), a git install, and a pip install are never replaced; upgrade a pip install with pip yourself. When the versions differ, Symphony opens a screen with **Update now** and **Not now**. Set `updates.auto` to install the newer release without that screen:

```json
{
  "updates": {
    "enabled": true,
    "auto": false
  }
}
```

`updates.enabled: false` skips the check. `SYMPHONY_NO_UPDATE_CHECK=1` skips it for one process. An unattended command updates only when `auto` is already true; otherwise it keeps the installed version instead of prompting. Run `symphony update` to update explicitly without reading the config. After a successful update, restart `symphony`. A failed download or install leaves the current version running.

Older Symphony releases can reject settings written by a newer release, including `theme`. If that older release does not support `symphony update`, upgrade it directly with `uv tool install --upgrade symphony-code`. This preserves the config file. Removing an unrecognized setting is also possible, but loses that setting.

## Tool approvals

By default, approval prompts are required for `bash`, overwriting an existing file, broad patches, and web searches. The coding-agent approval add-on—not the generic harness—implements these prompts. Deny rules are checked first and block a matching tool call; otherwise allow patterns skip a prompt. `approvals.deny` applies in every mode; `approvals.allow` skips prompts in ask mode. `Always allow` changes the active agent session and is not necessarily a persistent config edit.

Patterns match the bash command or the file path. A web search is matched as `web_search:<query>`, so a bash rule such as `git *` never applies to a search. For example, `"allow": ["web_search:*"]` stops the search prompt and `"deny": ["web_search:*"]` blocks every search. Setting `approvals.require_for_web_search` to `false` also stops the prompt.

**Approvals are not a sandbox.** Bash and workspace tools execute with the current user's permissions; absolute paths are available. A bare `CoreHarness` has no approval policy. Review [Security](../../SECURITY.md) before changing defaults or running unattended.

## Unattended runs

The headless `symphony run` command requires `--unattended` to acknowledge automatic approvals. Deny rules still apply, but they are not a containment mechanism. Use a disposable environment for tasks you cannot trust. See the [CLI reference](../reference/cli.md#symphony-run-headless-coding-run).

## Theme

`theme` in `config.json` is `"default"` or the name of a plugin theme such as `"dracula:Dracula"`. Set it with `/theme` or `symphony themes use`; see [themes](./themes.md).

## Skills and plugins

Skills are prompt files the model reads when they match the task; plugins package skills and addon code. Install and manage both from the shell or from the TUI with `symphony skills ...` / `/skills ...` and `symphony plugins ...` / `/plugins ...`; see the [plugin guide](./plugins.md), the [CLI reference](../reference/cli.md), and the [developer guide](../developer-guide/skills-and-plugins.md). Plugin state (installed, enabled) is kept in `plugins/state.json` under the Symphony home, not in `config.json`.

The `skills` and `plugins` sections of `config.json`:

```json
{
  "skills": {
    "enabled": true,
    "max_skills": 100,
    "max_context_tokens": 6000,
    "roots": [],
    "settings": {"orient": "name-only", "deploy": "manual"},
    "disabled": ["noisy-skill"]
  },
  "plugins": {"enabled": true}
}
```

- `max_context_tokens` (default 6000) bounds the skill catalog in the system prompt. Over budget, the longest descriptions are dropped first, then the last names; `/installed` shows each skill's token cost and what was trimmed.
- `settings` maps a skill name to `on` (name, description and path), `name-only`, or `manual` (not listed; point the model at its `SKILL.md` path yourself). `symphony skills mode` edits it.
- `disabled` skills are not loaded. `symphony skills disable` edits it.
- `plugins.enabled: false` turns every plugin off.

`plugins.entries` and `plugins.authorized_roots` are still accepted so a config written by 0.0.5 loads, but nothing reads them. `plugins.enabled` is the switch. Install plugins with `symphony plugins add`; enabled state is kept in `plugins/state.json`. Plugin addon code runs with your permissions while the plugin is enabled. Disable it with `symphony plugins disable <name>`.

## Context and optional integrations

The coding agent can warn about model context use and compact older conversation history. Use `/context` to inspect usage and `/compact` to request compaction. Details depend on the active model and product config.

Optional integrations have their own focused guides: [Langfuse tracing](./langfuse.md), [Jev completion checks](./jev.md), and [persistent learning](./learning.md).
