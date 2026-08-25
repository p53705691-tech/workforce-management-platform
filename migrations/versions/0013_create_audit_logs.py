"""create audit logs

Revision ID: 0013_create_audit_logs
Revises: 0012_create_employee_pay_rates
Create Date: 2026-08-25 00:00:11.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0013_create_audit_logs'
down_revision = '0012_create_employee_pay_rates'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.BigInteger(), nullable=True),
        sa.Column('actor_user_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.BigInteger(), nullable=True),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_audit_logs'),
        # organization_id/actor_user_id are both nullable (a failed login
        # for a nonexistent email establishes neither), so an ON DELETE
        # RESTRICT here only ever blocks deleting an organization/user
        # that a *populated* audit row still points to — never blocks
        # anything for NULL-context rows.
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            name='fk_audit_logs_organization_id_organizations',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['actor_user_id'], ['users.id'],
            name='fk_audit_logs_actor_user_id_users',
            ondelete='RESTRICT',
        ),
    )

    op.create_index(
        'ix_audit_logs_organization_id_entity_type_entity_id',
        'audit_logs',
        ['organization_id', 'entity_type', 'entity_id'],
    )
    op.create_index(
        'ix_audit_logs_actor_user_id_created_at',
        'audit_logs',
        ['actor_user_id', 'created_at'],
    )


def downgrade():
    op.drop_index(
        'ix_audit_logs_actor_user_id_created_at', table_name='audit_logs'
    )
    op.drop_index(
        'ix_audit_logs_organization_id_entity_type_entity_id',
        table_name='audit_logs',
    )
    op.drop_table('audit_logs')
