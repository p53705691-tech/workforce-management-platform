"""add audit_logs organization_id/created_at index

Round C fix: the only query against ``audit_logs``
(``app.services.audit.list_entries``) filters on
``(organization_id, created_at range)`` and orders by ``created_at
DESC``. The two existing indexes --
``(organization_id, entity_type, entity_id)`` and
``(actor_user_id, created_at)`` -- don't serve that access pattern, and
this table grows without bound (append-only, never pruned).

Revision ID: 0016_audit_logs_org_created_at
Revises: 0015_round_b_integrity
Create Date: 2026-08-25 09:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0016_audit_logs_org_created_at'
down_revision = '0015_round_b_integrity'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_audit_logs_organization_id_created_at',
        'audit_logs',
        ['organization_id', 'created_at'],
    )


def downgrade():
    op.drop_index(
        'ix_audit_logs_organization_id_created_at', table_name='audit_logs'
    )
