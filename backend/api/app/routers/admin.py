from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.schemas.admin import (
    AdminStatePatch,
    AuditResponse,
    EvalCreate,
    EvalList,
    EvalResponse,
    OrderResponse,
    Page,
    ProductResponse,
    StaffResponse,
    Status,
    StatusChange,
)
from app.services.admin_auth_service import admin_user, staff_user
from app.services.admin_service import AdminService, get_admin_service

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
