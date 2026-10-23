from fastapi import APIRouter, Depends, Query, Response

from app.core.errors import ApiError
from app.core.http import cache_for
from app.schemas.catalog import (
    CATEGORIES,
    LookDetailResponse,
    LooksResponse,
    ProductResponse,
    ProductsResponse,
    StoresResponse,
)
from app.services.catalog_service import CatalogService, get_catalog_service

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/products", response_model=ProductsResponse)
async def list_products(
    response: Response,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=20),
    ids: str | None = Query(default=None, max_length=2000),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductsResponse:
    if category and category not in CATEGORIES:
        raise ApiError(400, "Unknown category", "invalid_category")
    id_list = [s.strip() for s in ids.split(",") if s.strip()][:50] if ids else None
    query = q.strip()[:80] if q and q.strip() else None
    products = await service.list_products(q=query, category=category or None, ids=id_list)
    cache_for(response, 300)
    return ProductsResponse(products=products)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str, response: Response, service: CatalogService = Depends(get_catalog_service)
) -> ProductResponse:
    product = await service.get_product(product_id)
    if product is None:
        raise ApiError(404, "Product not found", "not_found")
    cache_for(response, 300)
    return ProductResponse(product=product)


@router.get("/looks", response_model=LooksResponse)
async def list_looks(
    response: Response, service: CatalogService = Depends(get_catalog_service)
) -> LooksResponse:
    looks = await service.list_looks()
    cache_for(response, 300)
    return LooksResponse(looks=looks)


@router.get("/looks/{look_id}", response_model=LookDetailResponse)
async def get_look(
    look_id: str, response: Response, service: CatalogService = Depends(get_catalog_service)
) -> LookDetailResponse:
    result = await service.get_look_with_products(look_id)
    if result is None:
        raise ApiError(404, "Look not found", "not_found")
    cache_for(response, 300)
    look, products = result
    return LookDetailResponse(look=look, products=products)


@router.get("/stores", response_model=StoresResponse)
async def list_stores(
    response: Response, service: CatalogService = Depends(get_catalog_service)
) -> StoresResponse:
    stores = await service.list_pickup_stores()
    cache_for(response, 3600)
    return StoresResponse(stores=stores)
