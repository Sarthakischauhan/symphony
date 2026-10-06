---
name: skill-discipline
description: Follow only the skills that change this task. Extra instructions make the agent worse.
args:
  - name: budget
    type: number
    description: Maximum number of other skills to read for one task.
    default: 4
---

Rank the catalog by how directly each skill applies.
Read at most `budget` skill files, plus this one.
Do not follow a skill you did not read.
