from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=12, ge=1, le=50)


class TaskResponse(BaseModel):
    id: str
    name: str
    description: str | None
    allowed_tools: list[str]
    max_steps: int
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskRunCreate(BaseModel):
    task_id: str
    input_data: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    id: str
    step_index: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskRunResponse(BaseModel):
    id: str
    task_id: str
    status: str
    current_step: int
    steps_log: list[dict[str, Any]]
    output: dict[str, Any] | None
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|deny)$")


class ScheduleCreate(BaseModel):
    task_id: str
    cron: str
    input_data: dict[str, Any] = Field(default_factory=dict)
