"""Cursor pagination. Cursor is an opaque base64 of the last (created_at, id)
so pagination is stable across inserts."""
import base64
import json
from datetime import datetime

from sqlalchemy import and_, or_


def encode_cursor(created_at: datetime, row_id: str) -> str:
    payload = {"c": created_at.isoformat(), "i": row_id}
    return base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(payload["c"]), payload["i"]
    except Exception:
        return None


def apply_cursor(stmt, model, cursor: str | None, *, order_by_created_desc: bool = True):
    """Adds a WHERE clause for `model.created_at < last_created_at OR (created_at = last AND id < last_id)`."""
    if not cursor:
        return stmt.order_by(model.created_at.desc(), model.id.desc())
    parsed = decode_cursor(cursor)
    if parsed is None:
        return stmt.order_by(model.created_at.desc(), model.id.desc())
    last_created, last_id = parsed
    return stmt.where(
        or_(
            model.created_at < last_created,
            and_(model.created_at == last_created, model.id < last_id),
        )
    ).order_by(model.created_at.desc(), model.id.desc())
