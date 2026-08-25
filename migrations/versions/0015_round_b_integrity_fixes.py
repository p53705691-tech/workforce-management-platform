"""round b: users composite-fk target, department_managers composite fk, missing indexes

Round B fixes:

1. ``users`` gains ``UniqueConstraint(id, organization_id)`` (uq_users_id)
   — the composite-FK target pattern already used by
   departments/employees/shifts, needed so department_managers.user_id
   can be tied to the manager's own organization at the database level.
2. ``department_managers.user_id`` was a plain FK to ``users.id`` with
   nothing asserting the user's organization matched the row's
   ``organization_id`` — a bad seed/manual insert could otherwise assign
   a manager from org A to a department in org B. The application
   happened to fail closed anyway (every scoped query independently
   filters by organization), but the invariant belongs in the database.
   Converted to a composite FK ``(user_id, organization_id) ->
   users(id, organization_id)``, same name, same CASCADE.
3. ``department_managers``' existing ``(department_id, organization_id)``
   FK gains an explicit ``ondelete='RESTRICT'`` for consistency with
   every other composite FK in the schema (previously implicit "NO
   ACTION" — functionally similar, but inconsistent).
4. Two missing indexes: ``employees(organization_id, department_id)``
   (supports every manager-scoped employee query) and
   ``attendance_entries(employee_id, business_date)`` (supports
   working_hours' worked_seconds_for_day/_week, called in tight per-day
   loops by cost/report calculations).

Revision ID: 0015_round_b_integrity
Revises: 0014_attendance_duration_chk
Create Date: 2026-08-25 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0015_round_b_integrity'
down_revision = '0014_attendance_duration_chk'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint('uq_users_id', 'users', ['id', 'organization_id'])

    op.drop_constraint(
        'fk_department_managers_user_id_users',
        'department_managers',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_department_managers_user_id_users',
        'department_managers',
        'users',
        ['user_id', 'organization_id'],
        ['id', 'organization_id'],
        ondelete='CASCADE',
    )

    op.drop_constraint(
        'fk_department_managers_department_id_departments',
        'department_managers',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_department_managers_department_id_departments',
        'department_managers',
        'departments',
        ['department_id', 'organization_id'],
        ['id', 'organization_id'],
        ondelete='RESTRICT',
    )

    op.create_index(
        'ix_employees_organization_id_department_id',
        'employees',
        ['organization_id', 'department_id'],
    )
    op.create_index(
        'ix_attendance_entries_employee_id_business_date',
        'attendance_entries',
        ['employee_id', 'business_date'],
    )


def downgrade():
    op.drop_index('ix_attendance_entries_employee_id_business_date', 'attendance_entries')
    op.drop_index('ix_employees_organization_id_department_id', 'employees')

    op.drop_constraint(
        'fk_department_managers_department_id_departments',
        'department_managers',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_department_managers_department_id_departments',
        'department_managers',
        'departments',
        ['department_id', 'organization_id'],
        ['id', 'organization_id'],
    )

    op.drop_constraint(
        'fk_department_managers_user_id_users',
        'department_managers',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_department_managers_user_id_users',
        'department_managers',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.drop_constraint('uq_users_id', 'users', type_='unique')
