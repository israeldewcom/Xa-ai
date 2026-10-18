from datetime import datetime
from pydantic import BaseModel


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    capability: str | None = None
    model_id: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
