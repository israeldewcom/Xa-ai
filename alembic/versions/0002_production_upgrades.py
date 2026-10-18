"""production upgrades — next_attempt_at on jobs

Revision ID: 0002
Revises: 0001
Create Date: 2025-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.drop_column("next_attempt_at")
