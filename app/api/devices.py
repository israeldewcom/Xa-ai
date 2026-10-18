import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import b64d, ed25519_verify, get_server_x25519_public_b64
from app.core.exceptions import AuthenticationError, NotFound, ValidationFailure
from app.database.models import Device, DeviceCommand, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.devices import (
    DeviceCommandCreate, DeviceCommandResponse, DevicePairingComplete,
    DevicePairingStartResponse, DeviceRegister, DeviceResponse, DeviceResultIn,
    DeviceServerKey,
)
from app.services import device_mesh

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("/server-key", response_model=DeviceServerKey)
async def server_key():
    return DeviceServerKey(server_x25519_pub=get_server_x25519_public_b64())


@router.post("", response_model=DeviceResponse, status_code=201)
async def register_device(
    payload: DeviceRegister,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(Device).where(
            Device.user_id == user.id, Device.name == payload.name,
        )
    )).scalar_one_or_none()
    if existing:
        raise ValidationFailure("Device name already in use.")
    count = len((await db.execute(
        select(Device).where(Device.user_id == user.id)
    )).scalars().all())
    from app.config import get_settings
    if count >= get_settings().device_max_per_user:
        raise ValidationFailure("Device limit reached.")

    dev = Device(
        user_id=user.id, name=payload.name, kind=payload.kind,
        capabilities=payload.capabilities,
        ed25519_pub=payload.ed25519_pub,
        x25519_pub=payload.x25519_pub,
    )
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return DeviceResponse.model_validate(dev)


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Device).where(Device.user_id == user.id).order_by(Device.created_at.desc())
    )).scalars().all()
    return [DeviceResponse.model_validate(d) for d in rows]


@router.post("/{device_id}/pair/start", response_model=DevicePairingStartResponse)
async def pair_start(
    device_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pairing = await device_mesh.start_pairing(db, user.id, device_id)
    return DevicePairingStartResponse(
        code=pairing.code, expires_at=pairing.expires_at,
    )


@router.post("/{device_id}/pair/complete", response_model=DeviceResponse)
async def pair_complete(
    request: Request, device_id: str, payload: DevicePairingComplete,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    await request.app.state.device_limiter.check(f"pair:{user.id}")
    device = await device_mesh.complete_pairing(db, user.id, device_id, payload.code)
    return DeviceResponse.model_validate(device)


async def get_device(
    request: Request,
    x_device_id: str = Header(...), x_device_ts: str = Header(...),
    x_device_sig: str = Header(...), db: AsyncSession = Depends(get_db),
) -> Device:
    """Device auth: Ed25519 signature over `{id}.{ts}.{METHOD}.{path}`."""
    dev = await db.get(Device, x_device_id)
    if dev is None or not dev.paired:
        raise AuthenticationError("Unknown or unpaired device.")
    try:
        ts = int(x_device_ts)
        sig = b64d(x_device_sig)
    except Exception:
        raise AuthenticationError("Malformed device auth.")
    if abs(time.time() - ts) > 60:
        raise AuthenticationError("Stale device timestamp.")
    msg = f"{dev.id}.{ts}.{request.method}.{request.url.path}".encode()
    if not ed25519_verify(dev.ed25519_pub, msg, sig):
        raise AuthenticationError("Bad device signature.")
    dev.online, dev.last_seen = True, datetime.now(timezone.utc)
    await db.commit()
    return dev


@router.get("/me/poll")
async def poll(dev: Device = Depends(get_device), db: AsyncSession = Depends(get_db)):
    cmds = await device_mesh.list_pending_for_device(db, dev.id)
    now = datetime.now(timezone.utc)
    out = []
    for c in cmds:
        c.status, c.delivered_at, c.attempts = "delivered", now, c.attempts + 1
        out.append({"id": c.id, "action": c.action, "payload_enc": c.payload_enc})
    await db.commit()
    return {"commands": out}


@router.post("/me/commands/{cmd_id}/result", status_code=204)
async def post_result(
    cmd_id: str, body: DeviceResultIn,
    dev: Device = Depends(get_device), db: AsyncSession = Depends(get_db),
):
    await device_mesh.complete_command(db, cmd_id, dev.id, body.result_enc, body.error_code)


@router.delete("/{device_id}", status_code=204)
async def revoke_device(
    device_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dev = await db.get(Device, device_id)
    if dev is None or dev.user_id != user.id:
        raise NotFound("Device not found.")
    await db.delete(dev)
    await db.commit()


@router.post("/{device_id}/commands", response_model=DeviceCommandResponse, status_code=201)
async def send_command(
    device_id: str, payload: DeviceCommandCreate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cmd = await device_mesh.enqueue_command(
        db, user.id, device_id, payload.action, payload.payload,
    )
    dev = await db.get(Device, device_id)
    result = device_mesh.decrypt_result(cmd, dev) if dev else None
    return DeviceCommandResponse(
        id=cmd.id, device_id=cmd.device_id, action=cmd.action,
        status=cmd.status, attempts=cmd.attempts, error_code=cmd.error_code,
        created_at=cmd.created_at, delivered_at=cmd.delivered_at,
        finished_at=cmd.finished_at, result=result,
    )


@router.get("/{device_id}/commands", response_model=list[DeviceCommandResponse])
async def list_commands(
    device_id: str, limit: int = 50,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    dev = await db.get(Device, device_id)
    if dev is None or dev.user_id != user.id:
        raise NotFound("Device not found.")
    rows = (await db.execute(
        select(DeviceCommand).where(DeviceCommand.device_id == device_id)
        .order_by(DeviceCommand.created_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    out = []
    for cmd in rows:
        result = device_mesh.decrypt_result(cmd, dev)
        out.append(DeviceCommandResponse(
            id=cmd.id, device_id=cmd.device_id, action=cmd.action,
            status=cmd.status, attempts=cmd.attempts, error_code=cmd.error_code,
            created_at=cmd.created_at, delivered_at=cmd.delivered_at,
            finished_at=cmd.finished_at, result=result,
        ))
    return out
