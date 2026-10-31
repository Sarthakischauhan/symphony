---
name: test-first
description: For a behavior change, add a failing test before production code, then make the smallest change that passes.
---

# Test first

Use this for a bug fix or a behavior change that the repo can test. Skip it for docs, generated files, and throwaway exploration.

1. Find the test command and the file that owns the behavior. Do not edit production code yet.
2. Add one test that fails because the behavior is missing, not because the test is broken. Run that test and keep the failure.
3. Write the smallest production change that makes it pass. Run the same test again.
4. If production code landed before the test, do not keep it as a reference. Replace it after the test fails for the right reason.
5. Add a test for each boundary this change can hit: empty input, one item, duplicates, a missing record, or an off-by-one. Do not invent cases the code cannot reach.
6. A green new test is not a green suite. Run the repo's targeted suite before calling the change done.
