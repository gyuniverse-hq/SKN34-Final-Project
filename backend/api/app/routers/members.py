from fastapi import APIRouter, Depends, Response

from app.core.auth import AuthUser, require_user
from app.schemas.member import (
    AgreeTermsRequest,
    CompleteAnalysisRequest,
    MeResponse,
    SkinAccess,
    TermsStatus,
)
from app.services.member_service import MemberService, get_member_service

router = APIRouter(prefix="/api", tags=["members"])


@router.get("/me", response_model=MeResponse)
async def me(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> MeResponse:
    return await service.me(user)


@router.post("/me/skin-access/first-ar-visit")
async def first_ar_visit(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> bool:
    return await service.first_ar_visit(user)


@router.get("/me/skin-access")
async def skin_access(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> SkinAccess:
    return await service.skin_access(user)


@router.post("/me/skin-access/dev-subscription")
async def start_dev_subscription(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> SkinAccess:
    return await service.start_dev_subscription(user)


@router.post("/me/skin-access/complete")
async def complete_analysis(
    body: CompleteAnalysisRequest,
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> SkinAccess:
    return await service.complete_analysis(user, body.run_id)


@router.post("/me/terms", response_model=TermsStatus)
async def agree_terms(
    body: AgreeTermsRequest,
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> TermsStatus:
    return await service.agree_terms(user, body.version)


@router.delete(
    "/me",
    status_code=204,
    responses={
        409: {"description": "Deletion in progress"},
        503: {"description": "Deletion unavailable"},
    },
)
async def delete_account(
    user: AuthUser = Depends(require_user),
    service: MemberService = Depends(get_member_service),
) -> Response:
    await service.delete_account(user)
    return Response(status_code=204)
