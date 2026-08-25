"""create attendance entries

Revision ID: 0009_create_attendance_entries
Revises: 0008_create_shifts
Create Date: 2026-08-24 00:00:07.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0009_create_attendance_entries'
down_revision = '0008_create_shifts'
branch_labels = None
depends_on = None


def upgrade():
    # attendance_entries.(shift_id, organization_id) needs this as its
    # composite FK target — same pattern already used by
    # employees/departments for their own child tables.
    op.create_unique_constraint('uq_shifts_id', 'shifts', ['id', 'organization_id'])

    op.create_table(
        'attendance_entries',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), nullable=False),
        sa.Column('shift_id', sa.BigInteger(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('business_date', sa.Date(), nullable=False),
        sa.Column(
            'break_minutes', sa.SmallInteger(), nullable=False, server_default='0'
        ),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('edited_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edit_reason', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_attendance_entries'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_attendance_entries_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Composite FK: the employee must belong to the same organization
        # as the entry itself (cross-tenant guard, same pattern as shifts).
        sa.ForeignKeyConstraint(
            ['employee_id', 'organization_id'],
            ['employees.id', 'employees.organization_id'],
            name='fk_attendance_entries_employee_id_employees',
            ondelete='RESTRICT',
        ),
        # Composite FK: a matched shift must belong to the same
        # organization as the entry. NULL shift_id (unscheduled work, or
        # no single unambiguous shift matched) bypasses this entirely.
        sa.ForeignKeyConstraint(
            ['shift_id', 'organization_id'],
            ['shifts.id', 'shifts.organization_id'],
            name='fk_attendance_entries_shift_id_shifts',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['created_by_user_id'], ['users.id'],
            name='fk_attendance_entries_created_by_user_id_users',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['edited_by_user_id'], ['users.id'],
            name='fk_attendance_entries_edited_by_user_id_users',
            ondelete='RESTRICT',
        ),
        # NOTE: CheckConstraint names below are given in the model's short
        # form (see migrations/env.py's target_metadata / app.models.base's
        # naming convention, and 0008_create_shifts's note on exactly this
        # point) so Alembic's naming-convention "ck" template adds the
        # "ck_attendance_entries_" prefix exactly once, matching the model.
        sa.CheckConstraint(
            'ended_at IS NULL OR ended_at > started_at', name='ended_after_started'
        ),
        # See app/models/attendance_entry.py's module docstring: 'open' and
        # 'needs_review' are both treated as "not yet closed" here, which
        # is what actually needs to be true of ended_at's nullability.
        sa.CheckConstraint(
            "(status IN ('open', 'needs_review')) = (ended_at IS NULL)",
            name='status_open_matches_ended_at_null',
        ),
        sa.CheckConstraint('break_minutes >= 0', name='break_minutes_non_negative'),
        sa.CheckConstraint(
            'ended_at IS NULL OR '
            'break_minutes * 60 < EXTRACT(EPOCH FROM (ended_at - started_at))',
            name='break_minutes_less_than_duration',
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'needs_review')", name='status_valid'
        ),
        sa.CheckConstraint(
            "source IN ('web', 'manual', 'import')", name='source_valid'
        ),
        sa.CheckConstraint(
            'edited_by_user_id IS NULL OR '
            '(edited_at IS NOT NULL AND edit_reason IS NOT NULL)',
            name='edit_requires_edited_at_and_reason',
        ),
    )

    # The actual duplicate-clock-in guarantee: at most one open (no
    # ended_at) entry per employee, enforced at the DB level via a partial
    # unique index (a plain UniqueConstraint cannot express the WHERE).
    op.create_index(
        'uq_attendance_entries_employee_id_open',
        'attendance_entries',
        ['employee_id'],
        unique=True,
        postgresql_where=sa.text('ended_at IS NULL'),
    )

    # No overlapping entries for the same employee, including an open
    # entry blocking any later one (an unbounded range still intersects).
    # Autogenerate cannot produce this DDL, so it is hand-written to match
    # exactly what `postgresql.ExcludeConstraint` in the model compiles
    # to, mirroring shifts' ex_shifts_employee_no_overlap exactly.
    op.execute(
        "ALTER TABLE attendance_entries ADD CONSTRAINT "
        "ex_attendance_entries_employee_no_overlap "
        "EXCLUDE USING gist ("
        "employee_id WITH =, "
        "tstzrange(started_at, ended_at) WITH &&"
        ")"
    )

    op.create_index(
        'ix_attendance_entries_employee_id_started_at',
        'attendance_entries',
        ['employee_id', 'started_at'],
    )
    op.create_index(
        'ix_attendance_entries_organization_id_business_date',
        'attendance_entries',
        ['organization_id', 'business_date'],
    )
    op.create_index(
        'ix_attendance_entries_shift_id', 'attendance_entries', ['shift_id']
    )


def downgrade():
    op.drop_index('ix_attendance_entries_shift_id', table_name='attendance_entries')
    op.drop_index(
        'ix_attendance_entries_organization_id_business_date',
        table_name='attendance_entries',
    )
    op.drop_index(
        'ix_attendance_entries_employee_id_started_at',
        table_name='attendance_entries',
    )
    op.drop_index(
        'uq_attendance_entries_employee_id_open', table_name='attendance_entries'
    )
    op.drop_table('attendance_entries')
    op.drop_constraint('uq_shifts_id', 'shifts', type_='unique')
