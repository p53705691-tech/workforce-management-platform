"""create organizations

Revision ID: 0002_create_organizations
Revises: 0001_enable_extensions
Create Date: 2026-08-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002_create_organizations'
down_revision = '0001_enable_extensions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organizations',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('slug', sa.Text(), nullable=False),
        sa.Column('timezone', sa.Text(), nullable=False, server_default='UTC'),
        sa.Column('currency_code', sa.CHAR(3), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_organizations'),
        sa.UniqueConstraint('slug', name='uq_organizations_slug'),
        # Short, unprefixed name: op.create_table binds to the app's real
        # naming convention (ck_%(table_name)s_%(constraint_name)s — see
        # migrations/env.py's target_metadata), which re-wraps whatever
        # name is given here. An already-prefixed name would be doubled
        # (ck_organizations_ck_organizations_...), exactly the bug fixed
        # for legacy databases by 0007_fix_check_constraint_names.py. This
        # short form matches app/models/organization.py's own
        # CheckConstraint(name=...) and the 0008+ migrations' convention,
        # so a fresh build never needs 0007's rename at all.
        sa.CheckConstraint(
            'char_length(currency_code) = 3',
            name='currency_code_length',
        ),
    )


def downgrade():
    op.drop_table('organizations')
