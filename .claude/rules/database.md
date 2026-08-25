---
paths:
  - "app/models/**/*.py"
  - "migrations/**/*.py"
---

# Database Rules

- PostgreSQL is the source of truth.
- Use SQLAlchemy for database access.
- Schema changes must use migrations.
- Never bypass the migration system for persistent schema changes.
- Use foreign keys for real relationships.
- Use unique constraints for real uniqueness requirements.
- Use check constraints when the invariant belongs in the database.
- Use NOT NULL when a value is required by the domain.
- Add indexes only when justified.
- Avoid accidental cascade deletes.
- Review relationship deletion behavior carefully.
- Use Decimal/Numeric for monetary values.
- Avoid storing unnecessary derived data.
- Define transaction boundaries for multi-step operations.
- Protect database integrity at the database layer when possible.
