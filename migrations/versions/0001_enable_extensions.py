"""enable extensions

Revision ID: 0001_enable_extensions
Revises:
Create Date: 2026-08-24 17:18:55.059929

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001_enable_extensions'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # btree_gist: enables GiST indexes on scalar types (used later for
    # exclusion constraints preventing overlapping shifts/attendance).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # citext: case-insensitive text type (used for email uniqueness).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade():
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
