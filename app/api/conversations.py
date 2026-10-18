from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, PermissionDenied
from app.database.models import Conversation, Message, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.conversations import ConversationResponse, MessageResponse
from app.schemas.pagination import Page
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=Page[ConversationResponse])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = apply_cursor(
        select(Conversation).where(Conversation.user_id == user.id),
        Conversation, cursor,
    ).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page(
        items=[ConversationResponse.model_validate(c) for c in items],
        next_cursor=next_cursor,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(Conversation, conversation_id)
    if c is None:
        raise NotFound("Conversation not found.")
    if c.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your conversation.")
    return ConversationResponse.model_validate(c)


@router.get("/{conversation_id}/messages", response_model=Page[MessageResponse])
async def list_messages(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(Conversation, conversation_id)
    if c is None:
        raise NotFound("Conversation not found.")
    if c.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your conversation.")
    stmt = apply_cursor(
        select(Message).where(Message.conversation_id == conversation_id),
        Message, cursor,
    ).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page(
        items=[MessageResponse.model_validate(m) for m in items],
        next_cursor=next_cursor,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(Conversation, conversation_id)
    if c is None:
        raise NotFound("Conversation not found.")
    if c.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your conversation.")
    await db.delete(c)
    await db.commit()
