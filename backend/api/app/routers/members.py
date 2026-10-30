from fastapi import APIRouter, Depends, Response

from app.core.auth import AuthUser, require_user
from app.schemas.member import AgreeTermsRequest, MeResponse, TermsStatus
from app.services.member_service import MemberService, get_member_service

router = APIRouter(prefix="/api", tags=["members"])


@router.get("/me", response_model=MeResponse)
async def me(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> MeResponse:
    return await service.me(user)


@router.post("/me/terms", response_model=TermsStatus)
async def agree_terms(
    body: AgreeTermsRequest,
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> TermsStatus:
    return await service.agree_terms(user, body.version)


@router.delete("/me", status_code=204)
async def delete_account(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> Response:
    await service.delete_account(user)
    return Response(status_code=204)
