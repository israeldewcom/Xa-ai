import logging
import math
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DocumentChunk, FileRecord
from app.services.storage import get_storage
from app.specialists.document import chunk, extract_text

logger = logging.getLogger("xa.retrieval")


async def index_file(
    db: AsyncSession, file_id: str, user_id: str,
    storage_key: str, mime: str,
) -> int:
    data = get_storage().get(storage_key)
    text = extract_text(mime, data)
    if not text.strip():
        return 0
    pieces = chunk(text)
    for i, content in enumerate(pieces):
        db.add(DocumentChunk(
            file_id=file_id, user_id=user_id,
            chunk_index=i, content=content, embedding=None,
        ))
    await db.commit()
    return len(pieces)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in text.split() if len(t) > 2]


def _score(query_tokens: list[str], doc: str) -> float:
    doc_tokens = Counter(_tokens(doc))
    if not doc_tokens:
        return 0.0
    overlap = sum(doc_tokens.get(t, 0) for t in query_tokens)
    norm = math.sqrt(sum(v * v for v in doc_tokens.values()))
    return overlap / (norm + 1e-9)


async def retrieve(
    db: AsyncSession, user_id: str, query: str, top_k: int = 4,
) -> list[dict]:
    rows = (await db.execute(
        select(DocumentChunk, FileRecord.filename)
        .join(FileRecord, FileRecord.id == DocumentChunk.file_id)
        .where(DocumentChunk.user_id == user_id)
    )).all()
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored = []
    for chunk_obj, filename in rows:
        s = _score(query_tokens, chunk_obj.content)
        if s > 0:
            scored.append({
                "file_id": chunk_obj.file_id,
                "filename": filename,
                "content": chunk_obj.content,
                "score": round(s, 4),
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
