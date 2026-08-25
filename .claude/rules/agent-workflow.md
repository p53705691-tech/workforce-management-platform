---
paths:
  - "**/*"
---

# Agent Workflow Rules

Use the appropriate specialist for complex work.

## Planning

For complex architectural changes:

Use:

- architect

before implementation.

## Implementation

Use:

- implementer

for substantial implementation work.

## Review

Meaningful features should receive:

- reviewer

Security-sensitive features should also receive:

- security-reviewer

Database-heavy changes should also receive:

- database-reviewer

Changes with significant business logic should also receive:

- testing-reviewer

User-facing workflows may receive:

- product-reviewer

## Final Gate

The final reviewer is authoritative for code quality review.

Do not consider a feature complete while CRITICAL or HIGH findings remain unresolved.

Never claim that a review was performed if it was not.

## Blocked Tool Calls

A permission rule or hook denial is never something to route around. If a
tool call is blocked:

1. Use an already-permitted tool or command that accomplishes the same
   legitimate goal.
2. If none exists, stop and report the exact blocker to the user rather than
   engineering a workaround (a differently-named script, a split command, an
   unrelated tool chosen specifically because a rule doesn't cover it).

This applies even when the blocked action would have been harmless — the
problem is defeating the control's purpose, not the specific outcome. State
plainly if a rule seems wrong or overly broad rather than deciding
unilaterally that it doesn't apply.
