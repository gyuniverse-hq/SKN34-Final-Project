from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from app.core.auth import AuthUser, require_user
from app.schemas.member import (
    AccountDeletionStatusRequest,
    AgreeTermsRequest,
    CompleteAnalysisRequest,
    MeResponse,
    SkinAccess,
    TermsStatus,
)
from app.schemas.reward import RewardWallet
from app.services.account_deletion_service import AccountDeletionPending
from app.services.member_service import MemberService, get_member_service
from app.services.reward_service import RewardService, get_reward_service

router = APIRouter(prefix="/api", tags=["members"])


@router.get("/me/rewards")
async def rewards(
    response: Response,
    user: AuthUser = Depends(require_user),
    service: RewardService = Depends(get_reward_service),
) -> RewardWallet:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.wallet(user.id)


@router.post("/me/rewards/attendance")
async def attend(
    user: AuthUser = Depends(require_user), service: RewardService = Depends(get_reward_service)
) -> RewardWallet:
    return await service.wallet(user.id, attend=True)


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
    try:
        await service.delete_account(user)
    except AccountDeletionPending as pending:
        body = {"error": pending.message, "code": pending.code}
        if pending.receipt:
            body["deletionReceipt"] = pending.receipt
        return JSONResponse(body, status_code=409, headers={"Cache-Control": "no-store"})
    return Response(status_code=204)


@router.post("/me/deletion-status")
async def account_deletion_status(
    body: AccountDeletionStatusRequest,
    service: MemberService = Depends(get_member_service),
) -> JSONResponse:
    status = await service.deletion_status(body.receipt)
    return JSONResponse({"status": status}, headers={"Cache-Control": "no-store"})
