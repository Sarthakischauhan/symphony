---
name: systematic-debug
description: Reproduce a failure, name one cause, then change one thing.
args:
  - name: repro
    type: string
    required: true
    description: Command, test name, or exact symptom that fails.
  - name: hypothesis
    type: string
    description: One suspected cause. Leave empty until there is evidence.
---

1. Run `repro` and keep the exact error. Do not edit while reading it.
2. Name the file and function that produced the failure.
3. If `hypothesis` is set, test that claim before inventing another.
4. Add a regression test that fails for this cause, then change only what the hypothesis requires.
5. Run the same repro and the new test. Do not disable the test or swallow the error.
