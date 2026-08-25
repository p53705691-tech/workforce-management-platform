"""create department_managers

Revision ID: 0006_create_department_managers
Revises: 0005_create_users
Create Date: 2026-08-24 00:00:04.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006_create_department_managers'
down_revision = '0005_create_users'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'department_managers',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=False),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            'user_id', 'department_id', name='pk_department_managers'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name='fk_department_managers_user_id_users',
            ondelete='CASCADE',
        ),
        # Composite FK: the managed department must belong to the same
        # organization recorded on this row (same tenant-consistency guard
        # used by every other composite FK in the schema).
        sa.ForeignKeyConstraint(
            ['department_id', 'organization_id'],
            ['departments.id', 'departments.organization_id'],
            name='fk_department_managers_department_id_departments',
        ),
    )


def downgrade():
    op.drop_table('department_managers')
