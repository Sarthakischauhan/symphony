---
name: context-budget
description: Read only the code the next decision needs.
args:
  - name: max_files
    type: number
    description: Most files to open before deciding on an edit.
    default: 4
---

Search first. Open at most `max_files` files, and only the relevant span.
Quote a path and a line, not a whole file.
