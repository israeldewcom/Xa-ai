from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class TrainingCreate(BaseModel):
    model_id: str
    dataset_reference: str
    training_method: str = "lora"
    configuration: dict[str, Any] = Field(default_factory=dict)


class TrainingResponse(BaseModel):
    id: str
    model_id: str
    dataset_reference: str
    training_method: str
    status: str
    artifact_reference: str | None = None
    metrics: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
