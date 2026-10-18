"""index on jobs.next_attempt_at so models and migrations agree

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Name matches SQLAlchemy's default for `index=True` on Job.next_attempt_at,
# so `alembic check` reports no drift.
_INDEX = "ix_jobs_next_attempt_at"


def upgrade() -> None:
    op.create_index(_INDEX, "jobs", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="jobs")
