import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, PermissionDenied
from app.database.models import User, Webhook
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.webhooks import WebhookCreate, WebhookResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    payload: WebhookCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    secret = payload.secret or secrets.token_urlsafe(32)
    hook = Webhook(
        user_id=user.id, url=str(payload.url),
        secret=secret, events=payload.events, active=True,
    )
    db.add(hook)
    await db.commit()
    await db.refresh(hook)
    return WebhookResponse.model_validate(hook)


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Webhook).where(Webhook.user_id == user.id)
    )).scalars().all()
    return [WebhookResponse.model_validate(h) for h in rows]


@router.delete("/{hook_id}", status_code=204)
async def delete_webhook(
    hook_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    h = await db.get(Webhook, hook_id)
    if h is None:
        raise NotFound("Webhook not found.")
    if h.user_id != user.id:
        raise PermissionDenied("Not your webhook.")
    h.active = False
    await db.commit()
