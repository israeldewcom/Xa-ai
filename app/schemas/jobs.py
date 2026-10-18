from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=64)
    input_reference: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    dead_lettered: bool
    next_attempt_at: datetime | None = None
    output_reference: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
