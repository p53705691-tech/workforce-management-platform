"""fix doubled check constraint names

Migrations 0002-0005 were hand-edited after being applied once, cleaning up
constraint names that originally duplicated the naming-convention prefix
(e.g. ck_organizations_ck_organizations_currency_code_length instead of
ck_organizations_currency_code_length). Any database migrated before that
edit still carries the old doubled names. This migration is idempotent: it
only renames a constraint if the old name is actually present, so it is a
no-op against a database that already has the clean names (e.g. one created
fresh from the corrected migration files) and a real fix against one that
doesn't.

Revision ID: 0007_fix_check_constraint_names
Revises: 0006_create_department_managers
Create Date: 2026-08-24 00:00:05.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0007_fix_check_constraint_names'
down_revision = '0006_create_department_managers'
branch_labels = None
depends_on = None

RENAMES = [
    ("employees", "ck_employees_ck_employees_employment_status_valid", "ck_employees_employment_status_valid"),
    ("employees", "ck_employees_ck_employees_first_name_not_blank", "ck_employees_first_name_not_blank"),
    ("employees", "ck_employees_ck_employees_last_name_not_blank", "ck_employees_last_name_not_blank"),
    ("employees", "ck_employees_ck_employees_pay_type_hourly_only", "ck_employees_pay_type_hourly_only"),
    ("employees", "ck_employees_ck_employees_terminated_on_after_hired_on", "ck_employees_terminated_on_after_hired_on"),
    ("employees", "ck_employees_ck_employees_terminated_status_matches_ter_9ff8", "ck_employees_terminated_status_matches_terminated_on"),
    ("employees", "ck_employees_ck_employees_weekly_contract_hours_range", "ck_employees_weekly_contract_hours_range"),
    ("organizations", "ck_organizations_ck_organizations_currency_code_length", "ck_organizations_currency_code_length"),
    ("users", "ck_users_ck_users_employee_role_requires_employee_id", "ck_users_employee_role_requires_employee_id"),
    ("users", "ck_users_ck_users_failed_login_count_non_negative", "ck_users_failed_login_count_non_negative"),
    ("users", "ck_users_ck_users_role_valid", "ck_users_role_valid"),
]


def _existing_check_constraint_names(conn, table_name):
    result = conn.execute(
        sa.text(
            "select conname from pg_constraint "
            "where conrelid = to_regclass(:t) and contype = 'c'"
        ),
        {"t": table_name},
    )
    return {row[0] for row in result}


def upgrade():
    conn = op.get_bind()
    for table_name, old_name, new_name in RENAMES:
        existing = _existing_check_constraint_names(conn, table_name)
        if old_name in existing:
            op.execute(f'ALTER TABLE {table_name} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')


def downgrade():
    conn = op.get_bind()
    for table_name, old_name, new_name in RENAMES:
        existing = _existing_check_constraint_names(conn, table_name)
        if new_name in existing:
            op.execute(f'ALTER TABLE {table_name} RENAME CONSTRAINT "{new_name}" TO "{old_name}"')
