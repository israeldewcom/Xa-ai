"""voice, devices, automation, quotas, cost, outbox

Revision ID: 0003
Revises: 0002
Create Date: 2025-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("conversation_id", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("total_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_voice_user", "voice_sessions", ["user_id"])
    op.create_index("ix_voice_status", "voice_sessions", ["status"])
    op.create_index("ix_voice_started", "voice_sessions", ["started_at"])

    op.create_table(
        "devices",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("ed25519_pub", sa.String(64), nullable=False),
        sa.Column("x25519_pub", sa.String(64), nullable=False),
        sa.Column("paired", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("trusted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("online", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_device_name"),
    )
    op.create_index("ix_dev_user", "devices", ["user_id"])
    op.create_index("ix_dev_paired", "devices", ["paired"])
    op.create_index("ix_dev_trusted", "devices", ["trusted"])
    op.create_index("ix_dev_online", "devices", ["online"])

    op.create_table(
        "device_pairings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_pairing_code"),
    )
    op.create_index("ix_pair_code", "device_pairings", ["code"])
    op.create_index("ix_pair_expires", "device_pairings", ["expires_at"])
    op.create_index("ix_pair_consumed", "device_pairings", ["consumed"])

    op.create_table(
        "device_commands",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("device_id", sa.String(32), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload_enc", sa.Text, nullable=False),
        sa.Column("result_enc", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_devcmd_device_status", "device_commands", ["device_id", "status"])
    op.create_index("ix_devcmd_expires", "device_commands", ["expires_at"])
    op.create_index("ix_devcmd_user", "device_commands", ["user_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("input_schema", sa.JSON, nullable=False),
        sa.Column("allowed_tools", sa.JSON, nullable=False),
        sa.Column("max_steps", sa.Integer, nullable=False, server_default="12"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_user", "tasks", ["user_id"])
    op.create_index("ix_tasks_enabled", "tasks", ["enabled"])

    op.create_table(
        "task_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("input_data", sa.JSON, nullable=False),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="0"),
        sa.Column("steps_log", sa.JSON, nullable=False),
        sa.Column("output", sa.JSON),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_detail", sa.Text),
        sa.Column("pending_approval_id", sa.String(32)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_taskruns_task", "task_runs", ["task_id"])
    op.create_index("ix_taskruns_status", "task_runs", ["status"])
    op.create_index("ix_taskruns_user_status", "task_runs", ["user_id", "status"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_index", sa.Integer, nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_toolcalls_run", "tool_calls", ["run_id"])
    op.create_index("ix_toolcalls_tool", "tool_calls", ["tool_name"])
    op.create_index("ix_toolcalls_status", "tool_calls", ["status"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(32)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approv_user", "approvals", ["user_id"])
    op.create_index("ix_approv_run", "approvals", ["run_id"])
    op.create_index("ix_approv_status", "approvals", ["status"])
    op.create_index("ix_approv_expires", "approvals", ["expires_at"])

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("cron", sa.String(128), nullable=False),
        sa.Column("input_data", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sched_user", "scheduled_tasks", ["user_id"])
    op.create_index("ix_sched_enabled", "scheduled_tasks", ["enabled"])
    op.create_index("ix_sched_next", "scheduled_tasks", ["next_run_at"])

    op.create_table(
        "daily_quotas",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("used", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "day", "key", name="uq_daily_quota"),
    )
    op.create_index("ix_quotas_user_day", "daily_quotas", ["user_id", "day"])
    op.create_index("ix_quotas_key", "daily_quotas", ["key"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(64)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("cost_micros", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("extra", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_user", "usage_events", ["user_id"])
    op.create_index("ix_usage_kind", "usage_events", ["kind"])
    op.create_index("ix_usage_created", "usage_events", ["created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_user", "outbox_events", ["user_id"])
    op.create_index("ix_outbox_event", "outbox_events", ["event"])
    op.create_index("ix_outbox_status_next", "outbox_events", ["status", "next_attempt_at"])

    op.create_table(
        "system_keys",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for t in [
        "system_keys", "outbox_events", "usage_events", "daily_quotas",
        "scheduled_tasks", "approvals", "tool_calls", "task_runs", "tasks",
        "device_commands", "device_pairings", "devices", "voice_sessions",
    ]:
        op.drop_table(t)
