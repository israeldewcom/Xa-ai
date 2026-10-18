from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)
    secret: str | None = Field(default=None, min_length=16, max_length=128)


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
