---
paths:
  - "**/*"
---

# Project Structure Rules

This is the canonical top-level layout for the application. All other
rule files (architecture, backend, database, domain, frontend, security,
testing, time-and-money, code-quality) are path-scoped against these
exact directories. If code is created under different top-level names,
those rules will silently stop applying.

Use:

- `app/` — Flask application code (routes, services, models)
- `app/models/` — SQLAlchemy models
- `migrations/` — Alembic migrations
- `templates/` — Jinja templates
- `static/` — CSS and vanilla JavaScript
- `tests/` — pytest tests

Do not introduce an alternative top-level layout (e.g. `src/`, `backend/`)
without updating every path-scoped rule file to match.

When bootstrapping the project for the first time, create this layout
before writing any feature code.
