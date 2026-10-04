"""mark seeded demo documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("is_seed", sa.Boolean, nullable=False, server_default=sa.false()))
    # Seeded files were stored under ".../seed-<name>" by app.seed.
    op.execute("UPDATE documents SET is_seed = true WHERE minio_key LIKE '%/seed-%'")


def downgrade() -> None:
    op.drop_column("documents", "is_seed")
