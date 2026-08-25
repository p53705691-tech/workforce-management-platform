---
paths:
  - "app/**/*.py"
  - "tests/**/*.py"
---

# Architecture Rules

- Keep the application as a modular monolith.
- Prefer simple, explicit architecture over unnecessary abstraction.
- Keep routes thin.
- Keep business logic outside HTTP handlers.
- Keep database access predictable and explicit.
- Prefer focused modules with clear responsibilities.
- Avoid God classes and God functions.
- Avoid circular dependencies.
- Avoid premature abstractions.
- Avoid unnecessary service/repository layers.
- Prefer composition over inheritance when practical.
- Reuse existing abstractions before creating new ones.
- Do not refactor unrelated code while implementing a feature.
- Prefer readability and maintainability over cleverness.
