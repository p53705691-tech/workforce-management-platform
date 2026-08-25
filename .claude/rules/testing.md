---
paths:
  - "tests/**/*.py"
  - "**/*_test.py"
---

# Testing Rules

Tests should verify behavior rather than implementation details.

Every meaningful business rule should have tests.

Prefer:

- unit tests for pure business logic
- integration tests for database behavior
- route tests for important HTTP flows

Test:

- happy paths
- invalid input
- authorization failures
- edge cases
- database constraints
- error handling
- time calculations
- monetary calculations

When fixing a bug:

1. Reproduce the bug.
2. Add or identify a regression test.
3. Fix the underlying problem.
4. Run the focused test.
5. Run the relevant broader suite.

Never weaken a test simply to make it pass.

Never delete a failing test without understanding why it exists.
