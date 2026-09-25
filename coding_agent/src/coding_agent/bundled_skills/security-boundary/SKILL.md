---
name: security-boundary
description: Validate at the boundary. Do not trust identifiers the client sends.
args:
  - name: boundary
    type: enum
    enum: [input, auth, query, output]
    required: false
    description: Which boundary this task crosses.
    default: input
  - name: threat
    type: string
    required: false
    description: The abuse this change must stop.
    default: ""
---

Hold the named `boundary`. Take identity from the verified session, parameterize queries, and do not log secrets.
If `threat` is set, say how the change stops it.
