---
name: verify-before-done
description: Do not claim a task is done until the check that would catch a regression has run.
args:
  - name: check
    type: string
    description: Command or observation that proves the change.
---

Use `check` when it is set. Otherwise pick the smallest command that fails if the change is wrong.
Run it and quote the result. If you cannot run it, say what is unverified.
