from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, require_user
from app.schemas.member import MeResponse

router = APIRouter(prefix="/api", tags=["members"])


@router.get("/me", response_model=MeResponse)
async def me(user: AuthUser = Depends(require_user)) -> MeResponse:
    return MeResponse(user=user)
