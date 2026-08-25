---
name: database-change
description: Safely implement PostgreSQL schema and data-model changes.
---

# Database Change

Before changing the database:

1. Inspect related models.
2. Inspect existing migrations.
3. Identify affected relationships.
4. Identify data-integrity risks.
5. Define constraints.
6. Implement the model change.
7. Create the migration.
8. Review the migration.
9. Test upgrade behavior.
10. Test relevant application behavior.

Pay special attention to:

- foreign keys
- uniqueness
- nullability
- indexes
- cascade behavior
- existing production data
