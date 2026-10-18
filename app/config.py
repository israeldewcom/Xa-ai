from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "XA AI"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost:8000"

    secret_key: str = "dev-only-change-me-please-this-is-not-safe"
    secret_key_previous: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    database_url: str = "sqlite+aiosqlite:///./xa_ai.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_connect_retries: int = 5

    redis_url: str | None = None

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./storage"
    max_upload_size_mb: int = 25
    max_request_body_mb: int = 30
    allowed_mime_types: list[str] = [
        "image/png", "image/jpeg", "image/webp", "image/gif",
        "application/pdf", "text/plain", "text/markdown",
        "audio/mpeg", "audio/wav", "audio/webm", "audio/ogg",
        "video/mp4", "video/webm",
    ]
    blocked_extensions: list[str] = [
        ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".com",
        ".msi", ".scr", ".ps1", ".vbs", ".js", ".jar", ".apk",
        ".app", ".dmg", ".pkg", ".deb", ".rpm", ".elf",
    ]
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_prefix: str = "xa-ai"

    inference_backend: Literal["openai_compatible", "stub"] = "stub"
    inference_base_url: str = "http://localhost:8080"
    inference_api_key: str | None = None
    inference_model_name: str = "qwen2.5-1.5b-instruct"
    inference_timeout_seconds: float = 120.0
    inference_max_tokens: int = 2048
    inference_max_retries: int = 3
    inference_cb_failure_threshold: int = 5
    inference_cb_recovery_seconds: int = 30

    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_model_name: str | None = None
    image_base_url: str | None = None
    audio_asr_base_url: str | None = None
    audio_asr_stream_url: str | None = None
    audio_tts_base_url: str | None = None
    audio_tts_stream_url: str | None = None
    audio_tts_voice: str = "alloy"
    embedding_base_url: str | None = None
    embedding_model_name: str | None = None
    embedding_batch_size: int = 32
    moderation_base_url: str | None = None

    voice_enabled: bool = True
    voice_sample_rate_hz: int = 16000
    voice_chunk_ms: int = 20
    voice_vad_aggressiveness: int = 2
    voice_vad_silence_ms: int = 700
    voice_vad_min_speech_ms: int = 200
    voice_max_utterance_seconds: int = 30
    voice_barge_in_enabled: bool = True
    voice_ws_auth_strict: bool = False  # reject ?token= in production if True

    device_enabled: bool = True
    device_pairing_ttl_seconds: int = 300
    device_command_ttl_seconds: int = 60
    device_max_per_user: int = 32
    device_heartbeat_seconds: int = 30
    device_command_max_attempts: int = 3

    automation_enabled: bool = True
    agent_max_steps: int = 12
    agent_step_timeout_seconds: int = 60
    agent_run_timeout_seconds: int = 600
    agent_require_approval_for: list[str] = [
        "shell", "file_write", "device_command", "http_post",
    ]
    # Phase 2.7 — shell is NOT granted by default. Operators must opt in.
    agent_allowed_tools: list[str] = [
        "fetch_url", "math", "llm_generate", "read_file", "write_file",
        "sleep", "device_command", "http_post",
    ]
    agent_max_concurrent_per_user: int = 3
    scheduler_enabled: bool = True

    outbound_block_private_ips: bool = True
    outbound_allow_hosts: list[str] = []
    outbound_timeout_seconds: float = 15.0
    outbound_max_redirects: int = 2

    quota_chat_per_day: int = 500
    quota_chat_tokens_per_day: int = 200_000
    quota_upload_mb_per_day: int = 200
    quota_jobs_per_day: int = 100
    quota_agent_runs_per_day: int = 50
    quota_voice_minutes_per_day: int = 60

    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 60
    rate_limit_upload_per_minute: int = 30
    rate_limit_admin_per_minute: int = 120
    rate_limit_voice_per_minute: int = 60
    rate_limit_device_per_minute: int = 120
    rate_limit_agent_per_minute: int = 20

    request_timeout_seconds: float = 180.0
    stream_heartbeat_seconds: int = 15

    idempotency_ttl_seconds: int = 86400
    idempotency_purge_interval_seconds: int = 600
    retention_messages_days: int = 365
    retention_audit_days: int = 730
    retention_voice_sessions_days: int = 30
    purge_interval_seconds: int = 3600
    orphan_voice_session_seconds: int = 3600

    worker_poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 300
    worker_heartbeat_seconds: int = 15
    job_max_attempts: int = 3
    job_backoff_base_seconds: int = 10
    job_backoff_jitter_seconds: int = 5

    webhook_timeout_seconds: float = 10.0
    webhook_max_retries: int = 3
    webhook_outbox_batch: int = 20
    webhook_outbox_interval: float = 2.0
    webhook_outbox_lease_seconds: int = 60

    training_workspace: str = "./training_workspace"
    training_enabled: bool = False

    cors_origins: list[str] = ["*"]

    @field_validator("secret_key")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("secret_key must be ≥ 16 characters")
        return v

    @field_validator("database_url")
    @classmethod
    def _fix_db(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @model_validator(mode="after")
    def _check_storage(self):
        if self.storage_backend == "s3":
            if not self.s3_bucket:
                raise ValueError("storage_backend=s3 requires s3_bucket")
            if not self.s3_region:
                raise ValueError("storage_backend=s3 requires s3_region")
        return self

    @model_validator(mode="after")
    def _check_prod(self):
        if self.environment == "production":
            problems = []
            if not self.redis_url:
                problems.append("REDIS_URL required in production")
            if "*" in self.cors_origins:
                problems.append("CORS wildcard forbidden in production")
            if self.debug:
                problems.append("DEBUG must be false in production")
            if "change" in self.secret_key.lower() or "dev-only" in self.secret_key.lower():
                problems.append("SECRET_KEY appears to be a placeholder")
            if self.inference_backend == "stub":
                problems.append(
                    "INFERENCE_BACKEND=stub in production would serve canned echo "
                    "replies as real AI output; point it at a real inference server"
                )
            if self.storage_backend == "local":
                problems.append(
                    "STORAGE_BACKEND=local is not durable on ephemeral hosts "
                    "(Render, containers); use s3"
                )
            if "shell" in self.agent_allowed_tools:
                problems.append(
                    "agent_allowed_tools includes 'shell' — remove it unless you "
                    "have sandboxed the host and accept the risk"
                )
            if problems:
                raise ValueError("Production config problems: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
