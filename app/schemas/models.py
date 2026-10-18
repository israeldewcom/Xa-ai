from datetime import datetime
from typing import Any
from pydantic import BaseModel


class ModelResponse(BaseModel):
    id: str
    name: str
    version: str
    capabilities: list[str]
    license: str
    runtime: str
    status: str
    enabled: bool

    model_config = {"from_attributes": True}


class EvaluationRequest(BaseModel):
    model_id: str
    dataset_version: str
    evaluation_type: str = "benchmark"
    config: dict[str, Any] = {}


class EvaluationResponse(BaseModel):
    id: str
    model_id: str
    dataset_version: str
    evaluation_type: str
    metrics: dict[str, Any]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
