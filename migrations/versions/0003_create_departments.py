"""create departments

Revision ID: 0003_create_departments
Revises: 0002_create_organizations
Create Date: 2026-08-24 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003_create_departments'
down_revision = '0002_create_organizations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'departments',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_departments'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_departments_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        # Every child table hangs a composite FK off (id, organization_id) so
        # the database itself enforces that a department's tenant always
        # matches the tenant of whatever references it (defense in depth
        # against cross-tenant data leaking through a mismatched FK).
        sa.UniqueConstraint('id', 'organization_id', name='uq_departments_id'),
        sa.UniqueConstraint('organization_id', 'code', name='uq_departments_organization_id'),
    )
    # Case-insensitive uniqueness of department name within an organization.
    # A functional unique index is the only way to express this in
    # PostgreSQL; it cannot be a plain UniqueConstraint.
    op.create_index(
        'uq_departments_organization_id_lower_name',
        'departments',
        ['organization_id', sa.text('lower(name)')],
        unique=True,
    )


def downgrade():
    op.drop_index('uq_departments_organization_id_lower_name', table_name='departments')
    op.drop_table('departments')
