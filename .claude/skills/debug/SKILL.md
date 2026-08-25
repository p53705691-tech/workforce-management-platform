---
name: debug
description: Systematically diagnose and fix bugs without weakening tests.
---

# Debug

Follow this order:

1. Reproduce the issue.
2. Identify the failing layer.
3. Inspect related code.
4. Determine the root cause.
5. Add or identify a regression test.
6. Fix the root cause.
7. Run the focused test.
8. Run relevant broader tests.
9. Inspect the final diff.

Never:

- randomly change code
- weaken tests
- delete tests
- hide errors
- make unrelated changes

Prefer root-cause fixes over patches.
