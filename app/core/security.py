import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.secrets import active_key, verify_keys

_s = get_settings()
_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, active_key(), algorithm=_s.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for key in verify_keys():
        try:
            return jwt.decode(token, key, algorithms=[_s.jwt_algorithm])
        except jwt.InvalidSignatureError as exc:
            last_exc = exc
            continue
    raise last_exc or jwt.InvalidTokenError("invalid token")


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode({
        "sub": user_id, "role": role, "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_s.access_token_expire_minutes)).timestamp()),
    })


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    jti = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=_s.refresh_token_expire_days)
    token = _encode({
        "sub": user_id, "jti": jti, "type": "refresh",
        "iat": int(now.timestamp()), "exp": int(expires.timestamp()),
    })
    return token, jti, expires


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw, prefix, hash)."""
    raw = "xa_" + secrets.token_urlsafe(32)
    prefix = raw[:10]
    return raw, prefix, hash_api_key(raw)


def require_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token.")
    return authorization.split(" ", 1)[1].strip()
