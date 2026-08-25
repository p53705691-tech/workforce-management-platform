"""create employees

Revision ID: 0004_create_employees
Revises: 0003_create_departments
Create Date: 2026-08-24 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT

# revision identifiers, used by Alembic.
revision = '0004_create_employees'
down_revision = '0003_create_departments'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'employees',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_number', sa.Text(), nullable=False),
        sa.Column('first_name', sa.Text(), nullable=False),
        sa.Column('last_name', sa.Text(), nullable=False),
        sa.Column('email', CITEXT(), nullable=True),
        sa.Column('phone', sa.Text(), nullable=True),
        sa.Column('employment_status', sa.Text(), nullable=False),
        sa.Column('pay_type', sa.Text(), nullable=False, server_default='hourly'),
        sa.Column('weekly_contract_hours', sa.Numeric(5, 2), nullable=True),
        sa.Column('hired_on', sa.Date(), nullable=False),
        sa.Column('terminated_on', sa.Date(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_employees'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_employees_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Composite FK: a row can only reference a department that belongs
        # to the same organization as the employee itself. This is the
        # database-level guard against a department from another tenant
        # being assigned to an employee.
        sa.ForeignKeyConstraint(
            ['department_id', 'organization_id'],
            ['departments.id', 'departments.organization_id'],
            name='fk_employees_department_id_departments',
            ondelete='RESTRICT',
        ),
        sa.UniqueConstraint('id', 'organization_id', name='uq_employees_id'),
        sa.UniqueConstraint(
            'organization_id', 'employee_number', name='uq_employees_organization_id'
        ),
        # Short, unprefixed names: op.create_table's naming convention
        # (see migrations/env.py's target_metadata) re-wraps whatever name
        # is given to a CheckConstraint, so an already-prefixed name would
        # be doubled (ck_employees_ck_employees_...) — see 0002's comment
        # and 0007_fix_check_constraint_names.py for the legacy-database
        # fix this avoids needing on a fresh build. Matches
        # app/models/employee.py's own CheckConstraint(name=...) values.
        sa.CheckConstraint(
            'length(trim(first_name)) > 0', name='first_name_not_blank'
        ),
        sa.CheckConstraint(
            'length(trim(last_name)) > 0', name='last_name_not_blank'
        ),
        sa.CheckConstraint(
            "employment_status IN ('active', 'inactive', 'terminated')",
            name='employment_status_valid',
        ),
        sa.CheckConstraint(
            "pay_type = 'hourly'", name='pay_type_hourly_only'
        ),
        sa.CheckConstraint(
            'weekly_contract_hours IS NULL OR '
            '(weekly_contract_hours >= 0 AND weekly_contract_hours <= 168)',
            name='weekly_contract_hours_range',
        ),
        sa.CheckConstraint(
            'terminated_on IS NULL OR terminated_on >= hired_on',
            name='terminated_on_after_hired_on',
        ),
        sa.CheckConstraint(
            "(employment_status = 'terminated') = (terminated_on IS NOT NULL)",
            name='terminated_status_matches_terminated_on',
        ),
    )
    # Partial unique index: email uniqueness only applies to rows that have
    # one. NULL emails (not every employee needs system contact info) must
    # not collide with each other under a plain UNIQUE constraint.
    op.create_index(
        'uq_employees_organization_id_email',
        'employees',
        ['organization_id', 'email'],
        unique=True,
        postgresql_where=sa.text('email IS NOT NULL'),
    )


def downgrade():
    op.drop_index('uq_employees_organization_id_email', table_name='employees')
    op.drop_table('employees')
