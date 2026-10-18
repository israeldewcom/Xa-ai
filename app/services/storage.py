import logging
import os
import re
from pathlib import Path
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger("xa.storage")
_s = get_settings()

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name)
    safe = _SAFE_NAME.sub("_", base)[:200]
    return safe or "file"


def generate_key(user_id: str, filename: str) -> str:
    import uuid
    return f"{user_id}/{uuid.uuid4().hex}_{filename}"


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "") -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def presigned_url(self, key: str, expires: int = 3600) -> str | None: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("key escapes root")
        return p

    def put(self, key: str, data: bytes, content_type: str = "") -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._p(key).unlink()
        except FileNotFoundError:
            pass

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        return None


class S3Storage:
    def __init__(self, cfg):
        import boto3
        self.bucket = cfg.s3_bucket
        self.prefix = cfg.s3_prefix
        self._client = boto3.client(
            "s3",
            region_name=cfg.s3_region,
            endpoint_url=cfg.s3_endpoint_url,
            aws_access_key_id=cfg.s3_access_key_id,
            aws_secret_access_key=cfg.s3_secret_access_key,
        )

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}"

    def put(self, key: str, data: bytes, content_type: str = "") -> None:
        self._client.put_object(
            Bucket=self.bucket, Key=self._k(key), Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    def get(self, key: str) -> bytes:
        r = self._client.get_object(Bucket=self.bucket, Key=self._k(key))
        return r["Body"].read()

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._k(key))
        except Exception:
            pass

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._k(key)},
            ExpiresIn=expires,
        )


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        if _s.storage_backend == "s3":
            _storage = S3Storage(_s)
        else:
            _storage = LocalStorage(_s.local_storage_path)
    return _storage
