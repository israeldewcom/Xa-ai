import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database.types import UTCDateTime


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="user", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_now, onupdate=_now, index=True,
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    capability: Mapped[str | None] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="completed", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class ModelRecord(Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("name", name="uq_models_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), index=True)
    model_identifier: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(32), default="1")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    license: Mapped[str] = mapped_column(String(64), default="unknown")
    runtime: Mapped[str] = mapped_column(String(64), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="configured", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class FileRecord(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(127), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_doc_chunk_file_idx", "file_id", "chunk_index"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_type_status", "job_type", "status"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dead_lettered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    input_reference: Mapped[str | None] = mapped_column(Text)
    output_reference: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    model_id: Mapped[str] = mapped_column(String(64), index=True)
    dataset_version: Mapped[str] = mapped_column(String(64))
    evaluation_type: Mapped[str] = mapped_column(String(64))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class TrainingRun(Base):
    __tablename__ = "training_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(64))
    dataset_reference: Mapped[str] = mapped_column(String(512))
    training_method: Mapped[str] = mapped_column(String(64), default="lora")
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    artifact_reference: Mapped[str | None] = mapped_column(String(512))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "route", "key", name="uq_idempotency"),
        Index("ix_idem_expires", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(128))
    route: Mapped[str] = mapped_column(String(128))
    status_code: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    worker_kind: Mapped[str] = mapped_column(String(32), index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
    current_job_id: Mapped[str | None] = mapped_column(String(32))


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    secret: Mapped[str] = mapped_column(String(128))
    events: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class DailyQuota(Base):
    __tablename__ = "daily_quotas"
    __table_args__ = (
        UniqueConstraint("user_id", "day", "key", name="uq_daily_quota"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    used: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    model_id: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_status_next", "status", "next_attempt_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_device_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32), default="unknown")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    ed25519_pub: Mapped[str] = mapped_column(String(64))
    x25519_pub: Mapped[str] = mapped_column(String(64))
    paired: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class DevicePairing(Base):
    __tablename__ = "device_pairings"
    __table_args__ = (UniqueConstraint("code", name="uq_pairing_code"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(8), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    __table_args__ = (
        Index("ix_devcmd_device_status", "device_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(64))
    payload_enc: Mapped[str] = mapped_column(Text)
    result_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    max_steps: Mapped[int] = mapped_column(Integer, default=12)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (Index("ix_taskrun_user_status", "user_id", "status"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    steps_log: Mapped[list] = mapped_column(JSON, default=list)
    output: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    pending_approval_id: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("task_runs.id", ondelete="CASCADE"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    cron: Mapped[str] = mapped_column(String(128))
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class SystemKey(Base):
    """Persisted server keys (X25519, future signing keys). Survives
    SECRET_KEY rotation."""
    __tablename__ = "system_keys"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
