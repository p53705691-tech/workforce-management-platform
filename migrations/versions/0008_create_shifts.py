"""create shifts

Revision ID: 0008_create_shifts
Revises: 0007_fix_check_constraint_names
Create Date: 2026-08-24 00:00:06.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0008_create_shifts'
down_revision = '0007_fix_check_constraint_names'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shifts',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('business_date', sa.Date(), nullable=False),
        sa.Column(
            'break_minutes', sa.SmallInteger(), nullable=False, server_default='0'
        ),
        sa.Column('status', sa.Text(), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_shifts'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_shifts_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Composite FK: a shift's department must belong to the same
        # organization as the shift itself (same tenant-consistency guard
        # used throughout the schema).
        sa.ForeignKeyConstraint(
            ['department_id', 'organization_id'],
            ['departments.id', 'departments.organization_id'],
            name='fk_shifts_department_id_departments',
            ondelete='RESTRICT',
        ),
        # Composite FK: an assigned employee must belong to the same
        # organization as the shift. NULL employee_id (an open/unassigned
        # shift) bypasses this check entirely.
        sa.ForeignKeyConstraint(
            ['employee_id', 'organization_id'],
            ['employees.id', 'employees.organization_id'],
            name='fk_shifts_employee_id_employees',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['created_by_user_id'], ['users.id'],
            name='fk_shifts_created_by_user_id_users',
            ondelete='RESTRICT',
        ),
        # NOTE: CheckConstraint names below are given in the model's short
        # form (e.g. 'ends_after_starts'), not the fully-qualified
        # 'ck_shifts_ends_after_starts'. Alembic's op.create_table() builds
        # its Table against the app's real metadata naming convention
        # (see migrations/env.py's target_metadata), and that convention's
        # "ck" template is "ck_%(table_name)s_%(constraint_name)s" — it
        # re-applies the "ck_shifts_" prefix on top of whatever name is
        # given. Passing an already-prefixed name here would double it
        # (exactly the bug 0007 had to clean up for employees/organizations
        # /users); passing the short name lets the convention add the
        # prefix exactly once, matching the model precisely.
        sa.CheckConstraint('ends_at > starts_at', name='ends_after_starts'),
        sa.CheckConstraint('break_minutes >= 0', name='break_minutes_non_negative'),
        # A break cannot consume the entire shift: the break, in seconds,
        # must be strictly less than the shift's total duration.
        sa.CheckConstraint(
            'break_minutes * 60 < EXTRACT(EPOCH FROM (ends_at - starts_at))',
            name='break_minutes_less_than_duration',
        ),
        # Sanity cap (confirmed rule A7): no single shift may span more
        # than 24 hours, overnight or not.
        sa.CheckConstraint(
            "ends_at - starts_at <= interval '24 hours'",
            name='duration_max_24_hours',
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')",
            name='status_valid',
        ),
        sa.CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name='published_at_matches_status',
        ),
    )
    # Core data-integrity guarantee: an employee cannot be booked onto two
    # overlapping shifts. Cancelled shifts and unassigned (employee_id IS
    # NULL) shifts are excluded from the check. Autogenerate cannot produce
    # this DDL, so it is hand-written to match exactly what
    # `postgresql.ExcludeConstraint` in the model compiles to (verified by
    # `flask db check` reporting zero drift once applied).
    op.execute(
        "ALTER TABLE shifts ADD CONSTRAINT ex_shifts_employee_no_overlap "
        "EXCLUDE USING gist ("
        "employee_id WITH =, "
        "tstzrange(starts_at, ends_at) WITH &&"
        ") WHERE (employee_id IS NOT NULL AND status <> 'cancelled')"
    )
    op.create_index(
        'ix_shifts_organization_id_department_id_starts_at',
        'shifts',
        ['organization_id', 'department_id', 'starts_at'],
    )
    op.create_index(
        'ix_shifts_employee_id_starts_at', 'shifts', ['employee_id', 'starts_at']
    )
    op.create_index(
        'ix_shifts_organization_id_business_date',
        'shifts',
        ['organization_id', 'business_date'],
    )


def downgrade():
    op.drop_index('ix_shifts_organization_id_business_date', table_name='shifts')
    op.drop_index('ix_shifts_employee_id_starts_at', table_name='shifts')
    op.drop_index(
        'ix_shifts_organization_id_department_id_starts_at', table_name='shifts'
    )
    op.drop_table('shifts')
