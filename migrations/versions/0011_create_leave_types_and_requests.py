"""create leave types and requests

Revision ID: 0011_leave_types_requests
Revises: 0010_overtime_policies_tiers
Create Date: 2026-08-24 00:00:09.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is varchar(32); the fuller name
# "0011_create_leave_types_and_requests" (37 chars) doesn't fit, so this
# revision id is shortened while the migration's docstring/filename stay
# descriptive — same convention as 0010.
revision = '0011_leave_types_requests'
down_revision = '0010_overtime_policies_tiers'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'leave_types',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('is_paid', sa.Boolean(), nullable=False),
        sa.Column(
            'requires_approval', sa.Boolean(), nullable=False, server_default='true'
        ),
        sa.Column(
            'blocks_scheduling', sa.Boolean(), nullable=False, server_default='true'
        ),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_leave_types'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_leave_types_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # NOTE: constraint names below use only the first column (matching
        # the model's naming convention "uq": "uq_%(table_name)s_%(column_0_name)s"
        # — see migrations/versions/0003_create_departments.py's identical
        # pattern for this exact point).
        sa.UniqueConstraint('organization_id', 'code', name='uq_leave_types_organization_id'),
        # Target for the composite FK from leave_requests.(leave_type_id,
        # organization_id) — same pattern already used for
        # departments/employees/shifts.
        sa.UniqueConstraint('id', 'organization_id', name='uq_leave_types_id'),
    )

    op.create_table(
        'leave_requests',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), nullable=False),
        sa.Column('leave_type_id', sa.BigInteger(), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('requested_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('decided_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_leave_requests'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_leave_requests_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Composite FK: the employee must belong to the same organization
        # as the request itself (cross-tenant guard, same pattern as
        # shifts/attendance entries).
        sa.ForeignKeyConstraint(
            ['employee_id', 'organization_id'],
            ['employees.id', 'employees.organization_id'],
            name='fk_leave_requests_employee_id_employees',
            ondelete='RESTRICT',
        ),
        # Composite FK: the leave type must belong to the same
        # organization as the request itself.
        sa.ForeignKeyConstraint(
            ['leave_type_id', 'organization_id'],
            ['leave_types.id', 'leave_types.organization_id'],
            name='fk_leave_requests_leave_type_id_leave_types',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['requested_by_user_id'], ['users.id'],
            name='fk_leave_requests_requested_by_user_id_users',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['decided_by_user_id'], ['users.id'],
            name='fk_leave_requests_decided_by_user_id_users',
            ondelete='RESTRICT',
        ),
        # NOTE: CheckConstraint names below are given in the model's short
        # form so Alembic's naming-convention "ck" template adds the
        # "ck_leave_requests_" prefix exactly once, matching the model —
        # see 0008_create_shifts's note on exactly this point.
        sa.CheckConstraint('ends_at > starts_at', name='ends_after_starts'),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name='status_valid',
        ),
        # See app/models/leave_request.py's module docstring: the literal
        # spec's single biconditional CHECK would force a
        # previously-approved-then-cancelled request's decision fields
        # back to NULL (since 'cancelled' isn't in ('approved',
        # 'rejected')), erasing exactly the history the confirmed
        # "distinguishable via the status column alone" business rule
        # needs kept. Split into two: pairing (always) + status-matching
        # (exempting 'cancelled', which carries over its prior state).
        sa.CheckConstraint(
            '(decided_by_user_id IS NULL) = (decided_at IS NULL)',
            name='decision_fields_paired',
        ),
        sa.CheckConstraint(
            "status = 'cancelled' OR "
            "(status IN ('approved', 'rejected')) = (decided_by_user_id IS NOT NULL)",
            name='decision_matches_status',
        ),
    )

    # No overlapping pending/approved leave for the same employee.
    # Rejected/cancelled requests are excluded from the check. Autogenerate
    # cannot produce this DDL, so it is hand-written to match exactly what
    # `postgresql.ExcludeConstraint` in the model compiles to (verified by
    # `flask db check` reporting zero drift once applied) — mirrors
    # shifts' ex_shifts_employee_no_overlap exactly.
    op.execute(
        "ALTER TABLE leave_requests ADD CONSTRAINT "
        "ex_leave_requests_employee_no_overlap "
        "EXCLUDE USING gist ("
        "employee_id WITH =, "
        "tstzrange(starts_at, ends_at) WITH &&"
        ") WHERE (status IN ('pending', 'approved'))"
    )

    op.create_index(
        'ix_leave_requests_employee_id_starts_at',
        'leave_requests',
        ['employee_id', 'starts_at'],
    )
    op.create_index(
        'ix_leave_requests_organization_id_status',
        'leave_requests',
        ['organization_id', 'status'],
    )


def downgrade():
    op.drop_index(
        'ix_leave_requests_organization_id_status', table_name='leave_requests'
    )
    op.drop_index(
        'ix_leave_requests_employee_id_starts_at', table_name='leave_requests'
    )
    op.drop_table('leave_requests')
    op.drop_table('leave_types')
