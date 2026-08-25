"""create overtime policies and tiers

Revision ID: 0010_overtime_policies_tiers
Revises: 0009_create_attendance_entries
Create Date: 2026-08-24 00:00:08.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is varchar(32); the fuller name
# "0010_create_overtime_policies_and_tiers" (39 chars) doesn't fit, so
# this revision id is shortened while the migration's docstring/filename
# stay descriptive.
revision = '0010_overtime_policies_tiers'
down_revision = '0009_create_attendance_entries'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'overtime_policies',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('daily_threshold_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('weekly_threshold_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column(
            'week_start_day', sa.SmallInteger(), nullable=False, server_default='0'
        ),
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
        sa.PrimaryKeyConstraint('id', name='pk_overtime_policies'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_overtime_policies_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # NOTE: short constraint names below (matching the model's
        # CheckConstraint(name=...)) so Alembic's naming-convention "ck"
        # template adds the "ck_overtime_policies_" prefix exactly once —
        # see 0008_create_shifts's note on exactly this point.
        sa.CheckConstraint(
            'daily_threshold_hours > 0 AND daily_threshold_hours <= 24',
            name='daily_threshold_hours_range',
        ),
        sa.CheckConstraint(
            'weekly_threshold_hours > 0 AND weekly_threshold_hours <= 168',
            name='weekly_threshold_hours_range',
        ),
        sa.CheckConstraint(
            'week_start_day BETWEEN 0 AND 6', name='week_start_day_range'
        ),
        sa.CheckConstraint(
            'effective_to IS NULL OR effective_to >= effective_from',
            name='effective_to_after_effective_from',
        ),
    )

    # Effective-dated exclusivity: exactly one policy in force per
    # organization per day. Autogenerate cannot produce this DDL, so it is
    # hand-written to match exactly what `postgresql.ExcludeConstraint` in
    # the model compiles to (verified standalone against Postgres, and
    # against pg_constraint once applied — see the model's docstring).
    # A NULL effective_to is treated as "still in force" (an unbounded
    # upper edge) by daterange() regardless of the '[]' bounds flag on
    # that side.
    op.execute(
        "ALTER TABLE overtime_policies ADD CONSTRAINT "
        "ex_overtime_policies_organization_no_overlap "
        "EXCLUDE USING gist ("
        "organization_id WITH =, "
        "daterange(effective_from, effective_to, '[]') WITH &&"
        ")"
    )

    op.create_table(
        'overtime_tiers',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('policy_id', sa.BigInteger(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('tier_order', sa.SmallInteger(), nullable=False),
        sa.Column('from_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('to_hours', sa.Numeric(5, 2), nullable=True),
        sa.Column('multiplier', sa.Numeric(4, 2), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_overtime_tiers'),
        sa.ForeignKeyConstraint(
            ['policy_id'], ['overtime_policies.id'],
            name='fk_overtime_tiers_policy_id_overtime_policies',
            ondelete='CASCADE',
        ),
        sa.CheckConstraint("scope IN ('daily', 'weekly')", name='scope_valid'),
        sa.CheckConstraint('tier_order >= 0', name='tier_order_non_negative'),
        sa.CheckConstraint('from_hours >= 0', name='from_hours_non_negative'),
        sa.CheckConstraint('multiplier > 0', name='multiplier_positive'),
        sa.CheckConstraint(
            'to_hours IS NULL OR to_hours > from_hours',
            name='to_hours_after_from_hours',
        ),
        sa.UniqueConstraint(
            'policy_id', 'scope', 'tier_order',
            name='uq_overtime_tiers_policy_id_scope_tier_order',
        ),
        sa.UniqueConstraint(
            'policy_id', 'scope', 'from_hours',
            name='uq_overtime_tiers_policy_id_scope_from_hours',
        ),
    )


def downgrade():
    op.drop_table('overtime_tiers')
    op.drop_table('overtime_policies')
