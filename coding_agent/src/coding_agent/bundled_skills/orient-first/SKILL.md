---
name: orient-first
description: Find the files that own the behavior before editing.
args:
  - name: focus
    type: string
    required: false
    description: Directory, feature, or symbol to map first.
    default: ""
  - name: depth
    type: enum
    enum: [sketch, thorough]
    required: false
    description: Sketch names the owners. Thorough also notes callers.
    default: sketch
---

Search, then read. Start at `focus` when it is set.
Name at most four owning files before any edit. At `depth: thorough`, add the callers.
