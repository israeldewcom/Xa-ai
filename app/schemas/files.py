from datetime import datetime
from pydantic import BaseModel


class FileResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FileDownloadUrl(BaseModel):
    url: str
    expires_in: int
