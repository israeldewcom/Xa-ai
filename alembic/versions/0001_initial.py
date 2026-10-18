"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rt_user", "refresh_tokens", ["user_id"])
    op.create_index("ix_rt_revoked", "refresh_tokens", ["revoked"])
    op.create_index("ix_rt_expires", "refresh_tokens", ["expires_at"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ak_user", "api_keys", ["user_id"])
    op.create_index("ix_ak_prefix", "api_keys", ["prefix"])
    op.create_index("ix_ak_revoked", "api_keys", ["revoked"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="New conversation"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conv_user", "conversations", ["user_id"])
    op.create_index("ix_conv_updated", "conversations", ["updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("capability", sa.String(32)),
        sa.Column("model_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_msg_conv", "messages", ["conversation_id"])
    op.create_index("ix_msg_status", "messages", ["status"])
    op.create_index("ix_msg_created", "messages", ["created_at"])

    op.create_table(
        "models",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("model_identifier", sa.String(255), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("license", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("runtime", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(32), nullable=False, server_default="configured"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_models_name"),
    )

    op.create_table(
        "files",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_files_user", "files", ["user_id"])
    op.create_index("ix_files_mime", "files", ["mime_type"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("file_id", sa.String(32), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.JSON),
    )
    op.create_index("ix_chunk_file_idx", "document_chunks", ["file_id", "chunk_index"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("dead_lettered", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("input_reference", sa.Text),
        sa.Column("output_reference", sa.Text),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_detail", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_jobs_type_status", "jobs", ["job_type", "status"])
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_user", "jobs", ["user_id"])
    op.create_index("ix_jobs_dead", "jobs", ["dead_lettered"])

    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("evaluation_type", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "training_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("dataset_reference", sa.String(512), nullable=False),
        sa.Column("training_method", sa.String(64), nullable=False, server_default="lora"),
        sa.Column("configuration", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("artifact_reference", sa.String(512)),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("actor_id", sa.String(32)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("meta", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_actor", "audit_events", ["actor_id"])
    op.create_index("ix_audit_action", "audit_events", ["action"])
    op.create_index("ix_audit_created", "audit_events", ["created_at"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("route", sa.String(128), nullable=False),
        sa.Column("status_code", sa.Integer),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "route", "key", name="uq_idempotency"),
    )
    op.create_index("ix_idem_user", "idempotency_records", ["user_id"])
    op.create_index("ix_idem_expires", "idempotency_records", ["expires_at"])

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        sa.Column("worker_kind", sa.String(32), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_job_id", sa.String(32)),
    )
    op.create_index("ix_wh_kind", "worker_heartbeats", ["worker_kind"])
    op.create_index("ix_wh_last_seen", "worker_heartbeats", ["last_seen"])

    op.create_table(
        "webhooks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_wh_user", "webhooks", ["user_id"])
    op.create_index("ix_wh_active", "webhooks", ["active"])


def downgrade() -> None:
    for t in [
        "webhooks", "worker_heartbeats", "idempotency_records",
        "audit_events", "training_runs", "model_evaluations", "jobs",
        "document_chunks", "files", "models", "messages", "conversations",
        "api_keys", "refresh_tokens", "users",
    ]:
        op.drop_table(t)
