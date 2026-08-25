---
paths:
  - "app/**/*.py"
  - "tests/**/*.py"
---

# Time and Money Rules

Time and money calculations are business-critical.

Use timezone-aware datetime handling where appropriate.

Keep storage, application, and display timezones clearly defined.

Do not mix naive and timezone-aware datetimes carelessly.

Consider:

- midnight
- overnight shifts
- missing clock-out
- duplicate clock-in
- early clock-in
- late clock-out
- overtime
- leave
- overlapping shifts

Never use floating-point arithmetic for monetary values.

Use Decimal and appropriate PostgreSQL numeric types.

Avoid premature rounding.

Round only at defined business boundaries.

Write tests for important time and money edge cases.
