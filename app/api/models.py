from fastapi import APIRouter, Depends

from app.dependencies import get_current_user, get_registry
from app.database.models import User
from app.orchestration.registry import ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_models(
    user: User = Depends(get_current_user),
    registry: ModelRegistry = Depends(get_registry),
):
    return {"models": registry.list_models()}
