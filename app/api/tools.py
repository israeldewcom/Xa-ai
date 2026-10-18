from fastapi import APIRouter, Depends

from app.config import get_settings
from app.database.models import User
from app.dependencies import get_current_user
from app.services.tools import tools_catalog

router = APIRouter(prefix="/tools", tags=["tools"])
_s = get_settings()


@router.get("")
async def list_tools(user: User = Depends(get_current_user)):
    return {"allowed": _s.agent_allowed_tools, "catalog": tools_catalog()}
