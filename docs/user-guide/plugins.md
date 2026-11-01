# Plugins

A plugin is a directory Symphony can install on your machine. It can add skills, which are instructions the model reads, and one addon, which is Python code Symphony loads. Installing copies the files. It does not run them. The addon runs later, while the plugin is enabled, with your user permissions.

## Install a plugin

From a shell, in any directory:

```sh
symphony plugins add ./my-plugin
symphony plugins add owner/repo
symphony plugins add https://github.com/owner/repo@v1
```

A source can be a local path, `owner/repo` on GitHub, or a git URL. Add `@ref` to the URL to select a branch, tag, or commit. If the plugin is inside a subdirectory of that source, add `--path DIR`.

To install from a marketplace, first add the catalog, then name the plugin:

```sh
symphony plugins marketplace add owner/marketplace-repo
symphony plugins add plugin-name@marketplace-name
```

The same commands work inside Symphony as `/plugins add ...`. After installing or enabling a plugin in a running session, start a new session so the agent reloads it.

## Where it is stored

`symphony plugins add` copies the plugin into the Symphony home (`~/.symphony`, or `$SYMPHONY_HOME` if that is set):

```text
~/.symphony/plugins/state.json
~/.symphony/plugins/marketplaces/<marketplace>/
~/.symphony/plugins/cache/<marketplace>/<plugin>/<version>/
```

`state.json` records what is installed and whether each plugin is enabled. Marketplace catalogs are copied under `marketplaces/`. The plugin files themselves are under `cache/`. Plugins installed without a marketplace use `direct` as the marketplace name.

A plugin checked into a project is not copied. Symphony finds it in `.symphony/plugins/<name>/` or `.agents/plugins/<name>/` in the workspace, then in parent directories up to the git root. It also looks in `~/.symphony/plugins/` and `~/.agents/plugins/` for plugins kept there by hand. The first plugin with a given name wins.

## Turn a plugin on or off

A newly installed plugin is enabled. While it is enabled, Symphony loads its skills and its addon. Disable it to stop both:

```sh
symphony plugins list
symphony plugins disable my-plugin
symphony plugins enable my-plugin
symphony plugins update my-plugin
symphony plugins remove my-plugin
```

`update` fetches the recorded source again and keeps the enabled state. `remove` deletes a plugin installed with `plugins add`; it does not delete a plugin that lives in your project. `plugins.enabled: false` in `~/.symphony/config.json` turns every plugin off.

## What a plugin looks like

Symphony reads the first manifest it finds, in this order: `plugin.json`, `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, or `.cursor-plugin/plugin.json`.

```text
my-plugin/
├── plugin.json
├── skills/
│   └── review/
│       └── SKILL.md
└── addons/
    └── review_notes/
        └── addon.py
```

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Review notes for the current change.",
  "skills": "./skills/",
  "extensions": {"symphony": {"addons": "./addons"}}
}
```

`name` is required. It starts with a letter or number and then contains at most 63 more letters, numbers, dots, underscores, or hyphens. `skills` defaults to `./skills/` and must stay inside the plugin. `extensions.symphony.addons` points at the addon directory and defaults to `addons`.

A skill is a `SKILL.md` file:

```markdown
---
name: review
description: Review the current diff before finishing.
---

Read the diff and report bugs before making any further edits.
```

Symphony puts the skill's name, description, and path in the prompt. The model reads the rest of the file with `read_file` when the task matches. A plugin skill is named `my-plugin:review`.

An addon is a directory under the declared addon root. It contains `addon.py` with a `setup(api)` function. See [Extending the harness](../developer-guide/extending.md) for the addon API. An addon runs with your permissions; enabling the plugin is the decision to allow that. Symphony does not sandbox it.

## What else is ignored

Symphony does not load every part another coding agent might ship in a plugin. Agents, slash commands, hooks, automations, MCP servers, apps, language servers, and output styles are skipped. `symphony plugins list` and `/installed` show each skipped part and why. The plugin's skills and Symphony addon still load.

## Make one locally

Create the tree above, then run:

```sh
symphony plugins add /absolute/path/to/my-plugin
symphony plugins list
```

The list shows the plugin's version, enabled state, scope, skill count, path, and anything Symphony skipped. Disable it with `symphony plugins disable my-plugin` if you do not want its code loaded.
