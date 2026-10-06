---
name: surgical-edit
description: Change only the lines the task requires. Do not refactor neighbors.
args:
  - name: scope
    type: string
    description: Files or symbols that are allowed to change.
---

If `scope` is set, edits outside it are out of bounds.
Match existing names and formatting. Do not add a helper for a one-time change.
