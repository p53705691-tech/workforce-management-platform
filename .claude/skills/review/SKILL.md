---
name: review
description: Run the project's complete review workflow for a completed feature.
---

# Review Workflow

Review the implementation in this order:

1. Run relevant tests.
2. Inspect git diff.
3. Run the master reviewer.
4. Run the security reviewer when security-sensitive.
5. Run the database reviewer when database changes exist.
6. Run the testing reviewer when business logic changed.
7. Run the product reviewer for user-facing workflows.
8. Fix blocking findings.
9. Run tests again.
10. Perform final diff inspection.

The feature is complete only when:

- tests pass
- no CRITICAL findings remain
- no HIGH findings remain
- the final diff is clean
