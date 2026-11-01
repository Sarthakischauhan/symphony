# Skills and plugins

Three things, three weights:

- A **skill** is a lazy prompt: a directory with a `SKILL.md`. Only one catalog line (name, description, absolute path) is in the system prompt. The model reads the body with the ordinary `read_file` tool when the task matches. Skills never run code and never need trust.
- An **addon** is code: a folder with `addon.py` and `setup(api)`, loaded by the existing addon runtime (see the [add-on guide](./extending.md)). Addons add no tools; tools live only in `tools/`.
- A **plugin** is a package that can carry skills and, optionally, one addon folder. Installing a plugin copies files and executes nothing.

The code is split the same way: `coding_agent/addons/skills/` (parse, catalog, install), `coding_agent/addons/plugins/` (manifest, marketplace, state, resolve, install, trust) and `coding_agent/extensions/` (the root order, diagnostics and sources that both share). `symphony skills`, `symphony plugins` and the `/skills`, `/plugins` slash commands are thin layers over those public functions (`coding_agent/commands/`). The plugins package never imports or runs plugin code: it hands the roots of enabled, trusted addons to `load_user_addons`.

## Where things are read from

One resolver (`extensions/roots.py`) orders every root, first match wins:

1. `.symphony/` and `.agents/` in the workspace, then each parent up to the git root (nearest first)
2. the Symphony home: `$SYMPHONY_HOME` or `~/.symphony`
3. `~/.agents` (shared with Codex, Pi, OpenCode and Grok)
4. skills bundled with Symphony

Each root has `skills/` and `plugins/`. A name found twice keeps the first one; the shadowed copy is reported as a notice in `/installed`, not an error. Project plugins are discovered in place, but their addon code needs `symphony plugins trust` like any other. Plain project skills load without trust because they are text.

Discovery problems (an unreadable manifest, a bad `SKILL.md`, a corrupt `state.json`) are diagnostics, never exceptions. They show in `/installed` and in the stdio `installed` result; the rest keeps loading. A plugin whose addon is not trusted shows as `addon not loaded: untrusted (run: symphony plugins trust <name>)` while its skills still load.

## Skills

A `SKILL.md` has front matter. Symphony reads these keys and ignores the rest:

```markdown
---
name: orient
description: Map the owners of a change before editing.
invocation: manual        # optional; "manual" keeps it out of the prompt
---
```

The catalog is one block in the system prompt:

```
Skills (when a skill matches the task, read its SKILL.md at the path shown before acting on that task):
- orient: Map the owners of a change before editing. (file: /home/me/.symphony/skills/orient/SKILL.md)
```

Plugin skills are namespaced `plugin:skill`. Descriptions are cut at 160 characters. The block is a pure function of the skill set and its settings: skills sort by name and trimming follows a fixed rule, so the prompt prefix stays byte-identical between runs and prompt caching works.

**Budget.** `skills.max_context_tokens` (default **6000**) bounds the whole block, header and lines. Over budget, the longest lines lose their descriptions first (name-only), then the last names in sorted order are omitted. Each trim is a notice, and `/installed` shows the token cost of every skill and the total. 6000 is sized so about 70 skills with full descriptions fit; the default of 2000 left installed collections such as pstack mostly name-only.

**Per-skill mode.** `symphony skills mode <name> on|name-only|manual|default`:

| Mode | In the prompt | How the model finds it |
| --- | --- | --- |
| `on` | name, description, path | the catalog line |
| `name-only` | name and path | the catalog line |
| `manual` | nothing | you point the model at the `SKILL.md` path yourself |
| off (`disable`) | nothing; not loaded | not available |

A skill without a setting is `manual` if its front matter says `invocation: manual`, else `on`.

### Installing a skill

`symphony skills add <source>` where source is a local path, a git URL with optional `@ref` (`https://github.com/o/r@v1`), or `owner/repo`. Every `SKILL.md` below the source is installed (a source that is itself a skill installs that one) into `~/.symphony/skills/<name>/`, or `.agents/skills/<name>/` in the project's git root with `--project`. Use `--path DIR` to pick a subdirectory. A provenance file `.symphony-source.json` is written beside each skill; `update` re-fetches from it and `remove` only deletes skills that carry it, so hand-written skills are never removed by the CLI.

## Plugins

### Manifest

The first of these that exists is read, in this order: `plugin.json`, `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`. Validation is a pydantic model; unknown keys are kept out of the way, not errors.

```json
{
  "name": "search",
  "version": "1.2.0",
  "description": "Search before opening files.",
  "skills": "./skills/",
  "extensions": {"symphony": {"addons": "./addons"}}
}
```

`name` is the plugin name; `skills` defaults to `./skills/`. A Symphony addon lives under `extensions.symphony.addons` and is a directory of addon folders.

### What loads and what does not

Symphony loads **skills** and, if trusted, one **addon**. Everything else a plugin can carry is detected from manifest keys and tree markers and listed as `skipped <part>: <reason>` on install, in `symphony plugins list <name>` output and in `/installed`. Nothing is faked:

| Contribution | Status |
| --- | --- |
| `skills/` | loaded (namespaced `plugin:skill`) |
| `extensions.symphony` addon | loaded only when trusted |
| `agents/` | skipped: plugin-defined agents are not supported |
| `commands/` | skipped: plugin slash commands are not supported |
| `hooks/`, `hooks.json` | skipped: hooks are not supported; Symphony runs plugin code only as a trusted addon |
| `automations/` | skipped: automations are not supported |
| `mcpServers`, `.mcp.json` | skipped: MCP servers are not supported yet |
| `.app.json`, `lspServers`, `outputStyles` | skipped |

### Marketplaces and sources

A marketplace is a catalog file in one of `.agents/plugins/marketplace.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/marketplace.json` (first found). A plugin entry's source is a relative path inside the marketplace, a local path, a git URL with a `ref` or `sha`, or a git subdirectory. Relative paths may not be absolute or contain `..`.

```
symphony plugins marketplace add michael-denyer/pstack-claude
symphony plugins add pstack@pstack-claude
symphony plugins add https://github.com/backnotprop/pstack
symphony plugins add ./my-plugin
```

Layout under the Symphony home:

```
plugins/state.json                         installed, enabled and trusted records
plugins/marketplaces/<marketplace>/        a copy of each added marketplace
plugins/cache/<marketplace>/<plugin>/<version>/   installed plugins ("direct" for plugins added without a marketplace)
```

Install stages the source in a hidden directory, validates it, then moves it into the cache; a failed install leaves nothing behind. Git sources are cloned with ext transports disabled, no hooks, no prompts, `.git` and symlinks dropped, a 64 MB cap and a 300 s timeout. `update` fetches again and keeps `enabled`; trust is kept only if the addon is byte-identical.

### Trust

**Plugin addon code runs with the same operating-system permissions as Symphony.** Trust is not a sandbox; see [Security](../../SECURITY.md). A plugin's addon is imported only if the plugin is enabled and `symphony plugins trust <name>` recorded its digest (SHA-256 over every file path and byte of the addon directory). Any change to the addon invalidates trust (`changed`) until you trust it again. Only `trust` writes trust; `add`, `update` and `enable` never do. `trust --revoke` withdraws it.

### Breaking changes

- The `plugins.entries` and `plugins.authorized_roots` config keys and `SYMPHONY_PLUGIN_AUTHORIZED_ROOTS` are removed; trust lives in `plugins/state.json`.
- The old `schema_version`/`id` `plugin.json` is no longer read; use the formats above.
- The `skill` tool is removed; skills are read with `read_file`.
- Project `.symphony/skills` load without trust.
- `skills.max_context_tokens` defaults to 6000.

### pstack

Both [backnotprop/pstack](https://github.com/backnotprop/pstack) (Cursor format) and [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude) (Claude marketplace plus `.agents/plugins`) install. Their skills load. Their `agents/`, `automations/` and hooks are listed as skipped. `coding_agent/tests/fixtures/pstack/` holds trimmed MIT-licensed copies with the upstream commits (`UPSTREAM.md`) so tests never use the network.

See the [add-on guide](./extending.md) for the harness hook API and the [configuration guide](../user-guide/configuration.md) for settings.
