from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class DeviceRegister(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="unknown", max_length=32)
    capabilities: list[str] = Field(default_factory=list)
    ed25519_pub: str = Field(min_length=32, max_length=64)
    x25519_pub: str = Field(min_length=32, max_length=64)


class DevicePairingStart(BaseModel):
    device_id: str


class DevicePairingStartResponse(BaseModel):
    code: str
    expires_at: datetime


class DevicePairingComplete(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")


class DeviceResultIn(BaseModel):
    result_enc: str | None = Field(default=None, max_length=200_000)
    error_code: str | None = Field(default=None, max_length=64)


class DeviceResponse(BaseModel):
    id: str
    name: str
    kind: str
    capabilities: list[str]
    paired: bool
    trusted: bool
    online: bool
    last_seen: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeviceCommandCreate(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class DeviceCommandResponse(BaseModel):
    id: str
    device_id: str
    action: str
    status: str
    attempts: int
    error_code: str | None = None
    created_at: datetime
    delivered_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class DeviceServerKey(BaseModel):
    server_x25519_pub: str
