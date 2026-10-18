from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.erasure import erase_user
from app.database.models import User
from app.database.session import get_db
from app.dependencies import get_current_user

router = APIRouter(prefix="/account", tags=["account"])


@router.delete("/erase", status_code=204)
async def erase_self(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await erase_user(db, user.id, actor_id=user.id)
