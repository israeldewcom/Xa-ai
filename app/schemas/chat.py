from typing import Any, Literal
from pydantic import BaseModel, Field


class Attachment(BaseModel):
    file_id: str
    kind: Literal["image", "audio", "video", "document", "text"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    conversation_id: str | None = None
    capability: Literal["auto", "text", "coding", "math", "health", "vision"] = "auto"
    attachments: list[Attachment] = Field(default_factory=list)
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    file_id: str
    score: float
    rank: int


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    content: str
    capability: str
    model: dict[str, Any]
    sources: list[Source] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
