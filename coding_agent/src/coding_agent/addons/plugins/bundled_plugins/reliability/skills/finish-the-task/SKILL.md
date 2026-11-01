---
name: finish-the-task
description: Do not stop at a partial edit. Finish the code, the tests, and a fresh verification run, and say what is still open.
---

# Finish the task

A task is not done when the first file compiles or the first test passes.

1. Restate the requested outcome in one sentence.
2. Check off code, tests, and verification separately. A missing check is still open.
3. Run the smallest command that fails if the change is wrong. Paste the result, including the exit status.
4. If a check cannot be run, say which one and why. Do not say "should pass" or "done" without that output.
5. The final answer names the files changed, the checks run, and anything left unverified.
