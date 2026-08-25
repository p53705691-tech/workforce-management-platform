"""create users

Revision ID: 0005_create_users
Revises: 0004_create_employees
Create Date: 2026-08-24 00:00:03.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT

# revision identifiers, used by Alembic.
revision = '0005_create_users'
down_revision = '0004_create_employees'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), nullable=True),
        sa.Column('email', CITEXT(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'failed_login_count', sa.SmallInteger(), nullable=False, server_default='0'
        ),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'password_changed_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_users'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_users_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Composite FK: an employee linked to a login must belong to the
        # same organization as the login itself. NULL employee_id (admins,
        # managers without an HR record) bypasses this check entirely,
        # which is correct: only employee-role users are required to link.
        sa.ForeignKeyConstraint(
            ['employee_id', 'organization_id'],
            ['employees.id', 'employees.organization_id'],
            name='fk_users_employee_id_employees',
            ondelete='RESTRICT',
        ),
        sa.UniqueConstraint('employee_id', name='uq_users_employee_id'),
        sa.UniqueConstraint('email', name='uq_users_email'),
        # Short, unprefixed names — see 0002's/0004's comments: an
        # already-prefixed CheckConstraint name gets doubled by the
        # naming convention op.create_table binds to. Matches
        # app/models/user.py's own CheckConstraint(name=...) values.
        sa.CheckConstraint(
            "role IN ('admin', 'manager', 'employee')", name='role_valid'
        ),
        sa.CheckConstraint(
            "role <> 'employee' OR employee_id IS NOT NULL",
            name='employee_role_requires_employee_id',
        ),
        sa.CheckConstraint(
            'failed_login_count >= 0', name='failed_login_count_non_negative'
        ),
    )


def downgrade():
    op.drop_table('users')
