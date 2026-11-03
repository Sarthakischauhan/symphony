# Themes

Plugins can ship color themes. Symphony reads them as data; installing a theme never runs code.

## Use a theme from the Claude marketplace

[claude-themes](https://github.com/matcra587/claude-themes) publishes Dracula, Nord, Gruvbox and others as plugins:

```sh
symphony plugins marketplace add matcra587/claude-themes
symphony plugins add dracula@claude-themes
symphony themes list
symphony themes use dracula
```

Inside Symphony, `/theme` opens a picker. Moving the highlight previews each theme on the whole screen. Enter keeps it and Esc puts the old one back. `/theme dracula` switches without the picker.

The choice is saved as `theme` in `config.json` (`"default"` unless you change it) and is applied the next time Symphony starts. Names are `<plugin>:<Theme Name>`, such as `dracula:Dracula (ANSI)`. A bare name works when only one plugin has it.

`~/.symphony/theme.toml` (or `$SYMPHONY_HOME/theme.toml`) still wins. If that file exists, it replaces the chosen theme completely and the picker says so.

## What a plugin provides

A plugin's `themes/` directory holds one file per theme:

- `*.json` in the Claude theme format: a `base` (`dark`, `light`, `dark-ansi`, `light-ansi`, or a daltonized variant) and an `overrides` map of Claude color slots.
- `*.toml` in Symphony's own shape: an optional `name` and `base`, and a `[colors]` table with the same keys as `theme.toml`.

A file that cannot be read is listed by `symphony plugins list` and skipped; the other themes still load.

## How Claude slots map to Symphony colors

| Claude slot | Symphony color |
| --- | --- |
| `text` | `foreground` |
| `subtle` | `muted` |
| `inactive` | `muted_dim` |
| `promptBorder` | `edge` |
| `claude` | `accent` |
| `success` | `string` |
| `error` | `keyword`, `type_keywords` |
| `warning` | `number` |
| `diffAdded`, `diffRemoved` | `diff_added`, `diff_removed` |
| `selectionBg` | `overlay` |
| `userMessageBackground` | `surface` |
| `clawd_background` | `background` |

Claude's own `background` slot is not used: in Claude it colors background-task labels, not the screen. A slot the theme leaves unset, or sets to something that is not a color, keeps the value from the palette of its `base`. Colors may be `#rrggbb`, `rgb(r,g,b)`, `ansi:<name>` or `ansi256(n)`.

## ANSI themes

A theme whose base ends in `-ansi` uses your terminal's own palette, so it looks like your terminal's colors. It leaves the terminal background alone, and code is highlighted with the terminal's ANSI colors. Other themes derive code colors from their own palette: Claude has no syntax colors, so Symphony borrows the theme's subagent hues.

## Limits

A theme recolors the top bar, composer, footer, transcript and code. Text already in the transcript keeps the colors it was written with. Some dialogs use fixed colors and do not follow the theme.
