---
paths:
  - "app/**/*.py"
---

# Backend Rules

- Follow the existing Flask architecture.
- Keep request handling separate from business logic.
- Validate external input at the application boundary.
- Never trust client-side validation.
- Handle errors intentionally.
- Never expose internal exceptions or stack traces to users.
- Prefer small functions with one responsibility.
- Prefer early returns when they improve readability.
- Avoid deeply nested conditionals.
- Avoid duplicated business logic.
- Use meaningful names.
- Keep database operations explicit.
- Do not introduce dependencies without a clear reason.
- Follow existing project conventions before introducing new patterns.
