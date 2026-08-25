"""create employee pay rates

Revision ID: 0012_create_employee_pay_rates
Revises: 0011_leave_types_requests
Create Date: 2026-08-24 00:00:10.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0012_create_employee_pay_rates'
down_revision = '0011_leave_types_requests'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'employee_pay_rates',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), nullable=False),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('hourly_rate', sa.Numeric(10, 4), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_employee_pay_rates'),
        # Composite FK: the rate's employee must belong to the same
        # organization as the rate row itself (cross-tenant guard, same
        # pattern as shifts/attendance/leave requests).
        sa.ForeignKeyConstraint(
            ['employee_id', 'organization_id'],
            ['employees.id', 'employees.organization_id'],
            name='fk_employee_pay_rates_employee_id_employees',
            ondelete='RESTRICT',
        ),
        # NOTE: CheckConstraint names below are given in the model's short
        # form so Alembic's naming-convention "ck" template adds the
        # "ck_employee_pay_rates_" prefix exactly once, matching the model
        # — see 0008_create_shifts's note on exactly this point.
        sa.CheckConstraint('hourly_rate > 0', name='hourly_rate_positive'),
        sa.CheckConstraint(
            'effective_to IS NULL OR effective_to >= effective_from',
            name='effective_to_after_effective_from',
        ),
    )

    # No two overlapping rate periods for the same employee. Autogenerate
    # cannot produce this DDL, so it is hand-written to match exactly what
    # `postgresql.ExcludeConstraint` in the model compiles to (verified by
    # `flask db check` reporting zero drift once applied) — mirrors
    # overtime_policies' ex_overtime_policies_organization_no_overlap
    # exactly, scoped to employee_id instead of organization_id. A NULL
    # effective_to is treated as "still in force" (an unbounded upper
    # edge) by daterange() regardless of the '[]' bounds flag on that
    # side.
    op.execute(
        "ALTER TABLE employee_pay_rates ADD CONSTRAINT "
        "ex_employee_pay_rates_employee_no_overlap "
        "EXCLUDE USING gist ("
        "employee_id WITH =, "
        "daterange(effective_from, effective_to, '[]') WITH &&"
        ")"
    )

    op.create_index(
        'ix_employee_pay_rates_employee_id_effective_from',
        'employee_pay_rates',
        ['employee_id', 'effective_from'],
    )


def downgrade():
    op.drop_index(
        'ix_employee_pay_rates_employee_id_effective_from',
        table_name='employee_pay_rates',
    )
    op.drop_table('employee_pay_rates')
