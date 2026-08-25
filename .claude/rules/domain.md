---
paths:
  - "app/**/*.py"
  - "tests/**/*.py"
---

# Workforce Management Domain Rules

The core domain contains:

- Employees
- Departments
- Shifts
- Attendance
- Working Hours
- Overtime
- Leave
- Labor Costs
- Reports

Keep these concepts separate.

A Shift represents planned work.

Attendance represents actual work activity.

Do not silently treat planned and actual work as the same thing.

Business rules must be explicit.

Do not invent business behavior.

When requirements are ambiguous, identify the ambiguity.

Reports must use authoritative data.

Derived values must have a clear source of truth.

Leave should interact correctly with scheduling and availability.

Authorization must respect organizational scope.

The core system must remain correct without AI.

Future AI features should consume reliable historical data from the core system.
