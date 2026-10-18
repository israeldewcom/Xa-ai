import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFound, ValidationFailure
from app.core.quotas import enforce
from app.core.rate_limit import RateLimiter
from app.database.models import FileRecord, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.files import FileDownloadUrl, FileResponse
from app.services.retrieval import index_file
from app.services.storage import generate_key, get_storage, sanitize_filename

logger = logging.getLogger("xa.api.files")
router = APIRouter(prefix="/files", tags=["files"])
_s = get_settings()

_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"%PDF", "application/pdf"),
    (b"OggS", "audio/ogg"),
    (b"\x1a\x45\xdf\xa3", "video/webm"),
    (b"fLaC", "audio/flac"),
]


def _detect(head: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _check_extension(filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext in _s.blocked_extensions:
        raise ValidationFailure(f"Blocked file extension: {ext}")


@router.post("", response_model=FileResponse, status_code=201)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limiter: RateLimiter = request.app.state.upload_limiter
    await limiter.check(f"upload:{user.id}")

    safe_name = sanitize_filename(file.filename or "upload")
    _check_extension(safe_name)

    # Chunked read with an incremental size cap (UploadFile is not async-iterable)
    max_bytes = _s.max_upload_size_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(64 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise ValidationFailure(f"File exceeds {_s.max_upload_size_mb} MB.")
    detected_mime = _detect(bytes(buf[:32]))

    mime = detected_mime or file.content_type or "application/octet-stream"
    if mime not in _s.allowed_mime_types:
        raise ValidationFailure(f"Unsupported file type: {mime}")

    await enforce(db, user.id, "upload_bytes", len(buf))

    key = generate_key(user.id, safe_name)
    # boto3 is synchronous: keep it off the event loop.
    await asyncio.to_thread(get_storage().put, key, bytes(buf), mime)

    rec = FileRecord(
        user_id=user.id, filename=safe_name,
        mime_type=mime, size_bytes=len(buf), storage_key=key,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    if mime in ("text/plain", "text/markdown", "application/pdf"):
        try:
            await index_file(db, rec.id, user.id, key, mime)
        except Exception:
            logger.exception("index_failed", extra={"file_id": rec.id})

    return FileResponse.model_validate(rec)


@router.get("/{file_id}", response_model=FileResponse)
async def meta(
    file_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(FileRecord, file_id)
    if rec is None:
        raise NotFound("File not found.")
    if rec.user_id != user.id and user.role != "admin":
        raise NotFound("File not found.")
    return FileResponse.model_validate(rec)


@router.get("/{file_id}/download")
async def download(
    file_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(FileRecord, file_id)
    if rec is None:
        raise NotFound("File not found.")
    if rec.user_id != user.id and user.role != "admin":
        raise NotFound("File not found.")
    data = await asyncio.to_thread(get_storage().get, rec.storage_key)
    return Response(content=data, media_type=rec.mime_type, headers={
        "Content-Disposition":
            f'attachment; filename="{sanitize_filename(rec.filename)}"',
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/{file_id}/url", response_model=FileDownloadUrl)
async def presigned(
    file_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(FileRecord, file_id)
    if rec is None:
        raise NotFound("File not found.")
    if rec.user_id != user.id and user.role != "admin":
        raise NotFound("File not found.")
    url = get_storage().presigned_url(rec.storage_key, expires=3600)
    if url is None:
        raise ValidationFailure("Presigned URLs require S3 storage backend.")
    return FileDownloadUrl(url=url, expires_in=3600)


@router.delete("/{file_id}", status_code=204)
async def delete(
    file_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(FileRecord, file_id)
    if rec is None:
        raise NotFound("File not found.")
    if rec.user_id != user.id and user.role != "admin":
        raise NotFound("File not found.")
    get_storage().delete(rec.storage_key)
    await db.delete(rec)
    await db.commit()
