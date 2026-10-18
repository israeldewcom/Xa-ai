from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class VoiceSessionCreate(BaseModel):
    conversation_id: str | None = None
    capability: Literal["auto", "text", "coding", "math", "health"] = "auto"
    tts_voice: str | None = None


class VoiceSessionResponse(BaseModel):
    id: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    total_seconds: int = 0
    turn_count: int = 0

    model_config = {"from_attributes": True}
