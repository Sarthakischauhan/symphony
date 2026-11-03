# pstack fixtures

Trimmed, unmodified copies of two MIT-licensed repositories, used so tests never touch the network.
Each copy keeps its own `LICENSE` (MIT). Files that are not copied: images, shell scripts, docs,
and all skills except the few listed here.

| Directory | Upstream | Commit | License |
| --- | --- | --- | --- |
| `pstack/` (Cursor format) | https://github.com/backnotprop/pstack | `25abb38559ddbabec563646224d09eff9a250eca` | MIT, (c) 2026 Lauren Tan |
| `pstack-claude/` (Claude + `.agents` marketplace) | https://github.com/michael-denyer/pstack-claude | `5851c89613e2ddc3a6b7f4af02a42363b30ef8d3` | MIT, (c) 2026 Lauren Tan, Michael Denyer |

The skills copied from `pstack-claude` (`bro`, `interrogate`, `principle-fix-root-causes`) are pstack-derived.
The skills that the upstream NOTICE attributes to cursor-team-kit and thermos (which have their own license
files upstream) are deliberately not included.
