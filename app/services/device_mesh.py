import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import (
    aes_gcm_decrypt, aes_gcm_encrypt, derive_device_channel_key,
    generate_x25519, set_server_x25519_private,
)
from app.core.exceptions import NotFound, PermissionDenied, ValidationFailure
from app.database.models import (
    Device, DeviceCommand, DevicePairing, SystemKey,
)

logger = logging.getLogger("xa.device_mesh")
_s = get_settings()


async def bootstrap_server_key(db: AsyncSession) -> None:
    """Load-or-create the persisted server X25519 key. This survives SECRET_KEY
    rotation, which is the whole point."""
    row = await db.get(SystemKey, "x25519")
    if row is None:
        priv_bytes, pub_b64 = generate_x25519()
        import base64
        row = SystemKey(
            name="x25519",
            value=base64.b64encode(priv_bytes).decode(),
        )
        db.add(row)
        await db.commit()
        logger.info("x25519_generated")
    import base64
    priv = base64.b64decode(row.value)
    set_server_x25519_private(priv)


def _aad(user_id: str, device_id: str, command_id: str) -> bytes:
    return f"cmd:{user_id}:{device_id}:{command_id}".encode()


async def start_pairing(
    db: AsyncSession, user_id: str, device_id: str,
) -> DevicePairing:
    device = await db.get(Device, device_id)
    if device is None or device.user_id != user_id:
        raise NotFound("Device not found.")
    if device.paired:
        raise ValidationFailure("Device already paired.")

    code = f"{secrets.randbelow(90_000_000) + 10_000_000}"
    pairing = DevicePairing(
        code=code, user_id=user_id, device_id=device_id,
        expires_at=datetime.now(timezone.utc) + timedelta(
            seconds=_s.device_pairing_ttl_seconds
        ),
    )
    db.add(pairing)
    await db.commit()
    await db.refresh(pairing)
    return pairing


async def complete_pairing(
    db: AsyncSession, user_id: str, device_id: str, code: str,
) -> Device:
    now = datetime.now(timezone.utc)
    pairing = (await db.execute(
        select(DevicePairing).where(
            and_(
                DevicePairing.code == code,
                DevicePairing.user_id == user_id,
                DevicePairing.device_id == device_id,
                DevicePairing.consumed.is_(False),
                DevicePairing.expires_at > now,
            )
        )
    )).scalar_one_or_none()
    if pairing is None:
        raise ValidationFailure("Invalid or expired pairing code.")
    device = await db.get(Device, pairing.device_id)
    if device is None:
        raise NotFound("Device not found.")
    device.paired = True
    device.trusted = True
    pairing.consumed = True
    await db.commit()
    return device


async def enqueue_command(
    db: AsyncSession, user_id: str, device_id: str, action: str, payload: dict,
) -> DeviceCommand:
    device = await db.get(Device, device_id)
    if device is None or device.user_id != user_id:
        raise NotFound("Device not found.")
    if not device.paired:
        raise ValidationFailure("Device not paired.")

    key = derive_device_channel_key(user_id, device_id, device.x25519_pub)
    cmd = DeviceCommand(
        device_id=device_id, user_id=user_id, action=action,
        payload_enc="",
        expires_at=datetime.now(timezone.utc) + timedelta(
            seconds=_s.device_command_ttl_seconds
        ),
        status="queued",
    )
    db.add(cmd)
    await db.flush()
    plaintext = json.dumps(payload).encode()
    cmd.payload_enc = aes_gcm_encrypt(
        key, plaintext, aad=_aad(user_id, device_id, cmd.id),
    )
    await db.commit()
    await db.refresh(cmd)
    return cmd


def decrypt_command(cmd: DeviceCommand, device: Device) -> dict:
    key = derive_device_channel_key(device.user_id, device.id, device.x25519_pub)
    plain = aes_gcm_decrypt(
        key, cmd.payload_enc, aad=_aad(device.user_id, device.id, cmd.id),
    )
    return json.loads(plain)


def encrypt_result(cmd: DeviceCommand, device: Device, result: dict) -> str:
    key = derive_device_channel_key(device.user_id, device.id, device.x25519_pub)
    return aes_gcm_encrypt(
        key, json.dumps(result).encode(),
        aad=_aad(device.user_id, device.id, cmd.id),
    )


def decrypt_result(cmd: DeviceCommand, device: Device) -> dict | None:
    if not cmd.result_enc:
        return None
    key = derive_device_channel_key(device.user_id, device.id, device.x25519_pub)
    plain = aes_gcm_decrypt(
        key, cmd.result_enc, aad=_aad(device.user_id, device.id, cmd.id),
    )
    return json.loads(plain)


async def list_pending_for_device(
    db: AsyncSession, device_id: str, limit: int = 10,
) -> list[DeviceCommand]:
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device_id,
            DeviceCommand.status == "queued",
            DeviceCommand.expires_at > now,
        ).order_by(DeviceCommand.created_at).limit(limit)
    )).scalars().all()
    return rows


async def complete_command(
    db: AsyncSession, command_id: str, device_id: str,
    result_enc: str | None = None, error_code: str | None = None,
) -> None:
    """The device returns an already-encrypted result; the server stores it
    opaquely and never needs the device's channel key to do so."""
    cmd = await db.get(DeviceCommand, command_id)
    if cmd is None or cmd.device_id != device_id:
        raise PermissionDenied("Not your command.")
    if cmd.status != "delivered":
        raise ValidationFailure("Command not in delivered state.")
    cmd.finished_at = datetime.now(timezone.utc)
    if error_code:
        cmd.status, cmd.error_code = "failed", error_code
    else:
        cmd.status, cmd.result_enc = "succeeded", result_enc or ""
    await db.commit()
