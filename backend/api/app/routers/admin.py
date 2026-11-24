from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.schemas.admin import (
    AdminStatePatch,
    AuditResponse,
    EvalCreate,
    EvalList,
    EvalResponse,
    LipEvalProduct,
    LipEvalProductList,
    LipTriadEvalResponse,
    OrderResponse,
    Page,
    ProductResponse,
    StaffResponse,
    Status,
    StatusChange,
)
from app.services.admin_auth_service import admin_user, staff_user
from app.services.admin_service import AdminService, get_admin_service
from app.services.lip_eval_panel_service import LipEvalPanelService, get_lip_eval_panel_service
from app.services.lip_triad_eval_service import LipTriadEvalService, get_lip_triad_eval_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/me", response_model=StaffResponse)
async def me(user=Depends(staff_user)):
    return user


@router.get("/audit-log", response_model=Page[AuditResponse])
async def audit_log(
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(admin_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.audit_list(cursor, limit)


@router.get("/orders", response_model=Page[OrderResponse])
async def orders(
    status: Status | None = None,
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(staff_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.orders(status, cursor, limit)


@router.get("/orders/{ident}", response_model=OrderResponse)
async def order(
    ident: str, user=Depends(staff_user), service: AdminService = Depends(get_admin_service)
):
    return await service.order(ident)


@router.post("/orders/{ident}/status", response_model=OrderResponse)
async def status_change(
    ident: str,
    body: StatusChange,
    user=Depends(admin_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.change_status(ident, body, user["userId"])


@router.get("/products", response_model=Page[ProductResponse])
async def products(
    query: str = Query("", max_length=100),
    category: str | None = None,
    cursor: str | None = Query(None, max_length=64),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(staff_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.products(query, category, cursor, limit)


@router.get("/products/{ident}", response_model=ProductResponse)
async def product(
    ident: str, user=Depends(staff_user), service: AdminService = Depends(get_admin_service)
):
    return await service.product(ident)


@router.patch("/products/{ident}/admin-state", response_model=ProductResponse)
async def patch_product(
    ident: str,
    body: AdminStatePatch,
    user=Depends(admin_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.patch_product(ident, body, user["userId"])


@router.post("/eval-runs", response_model=EvalResponse)
async def create_eval(
    body: EvalCreate, user=Depends(admin_user), service: AdminService = Depends(get_admin_service)
):
    return await service.create_eval(body, user["userId"])


@router.get("/eval-runs", response_model=EvalList)
async def eval_runs(
    kind: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(staff_user),
    service: AdminService = Depends(get_admin_service),
):
    return await service.eval_runs(kind, limit)


@router.get("/eval-runs/{ident}", response_model=EvalResponse)
async def eval_run(
    ident: UUID, user=Depends(staff_user), service: AdminService = Depends(get_admin_service)
):
    return await service.eval_run(ident)


@router.post("/lip-triad-eval", response_model=LipTriadEvalResponse)
async def lip_triad_eval(
    bare: UploadFile = File(..., description="화장 전(맨입술)"),
    real: UploadFile = File(..., description="실제로 바른 입술"),
    ar: UploadFile = File(..., description="AR 적용"),
    user=Depends(admin_user),
    service: LipTriadEvalService = Depends(get_lip_triad_eval_service),
):
    """Score technical metrics and Astra naturalness. Image bytes are discarded after scoring."""
    return await service.evaluate(bare, real, ar, user["userId"])


@router.get("/lip-eval/products", response_model=LipEvalProductList)
async def lip_eval_products(
    user=Depends(staff_user),
    service: LipEvalPanelService = Depends(get_lip_eval_panel_service),
):
    return await service.list_products()


@router.get("/lip-eval/products/{product_id}", response_model=LipEvalProduct)
async def lip_eval_product(
    product_id: str,
    user=Depends(staff_user),
    service: LipEvalPanelService = Depends(get_lip_eval_panel_service),
):
    return await service.get_product(product_id)


@router.post(
    "/lip-eval/products/{product_id}/raters/{rater_id}/refs", response_model=LipEvalProduct
)
async def lip_eval_save_refs(
    product_id: str,
    rater_id: int,
    bare: UploadFile = File(..., description="화장 전(맨입술)"),
    real: UploadFile = File(..., description="실제로 바른 입술"),
    user=Depends(admin_user),
    service: LipEvalPanelService = Depends(get_lip_eval_panel_service),
):
    """Save bare/real for a rater slot (eval-period retention)."""
    return await service.save_refs(product_id, rater_id, bare, real, user["userId"])


@router.post("/lip-eval/products/{product_id}/raters/{rater_id}/ar", response_model=LipEvalProduct)
async def lip_eval_score_ar(
    product_id: str,
    rater_id: int,
    ar: UploadFile = File(..., description="AR 적용"),
    user=Depends(admin_user),
    service: LipEvalPanelService = Depends(get_lip_eval_panel_service),
):
    """Score AR against stored bare/real for this product × rater slot."""
    return await service.score_ar(product_id, rater_id, ar, user["userId"])


@router.get("/lip-eval/products/{product_id}/raters/{rater_id}/images/{kind}")
async def lip_eval_image(
    product_id: str,
    rater_id: int,
    kind: str,
    user=Depends(staff_user),
    service: LipEvalPanelService = Depends(get_lip_eval_panel_service),
):
    data, mime = await service.read_image(product_id, rater_id, kind)
    return Response(content=data, media_type=mime)
