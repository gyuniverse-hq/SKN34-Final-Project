from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.core.errors import ApiError, UpstreamError
from app.core.http import cache_for
from app.core.ratelimit import RateLimiter, client_key, get_offer_search_rate_limiter
from app.schemas.catalog import (
    CATEGORIES,
    CONCERNS,
    LookDetailResponse,
    LooksResponse,
    ProductResponse,
    ProductsResponse,
    StoresResponse,
)
from app.schemas.catalog_options import (
    OptionCategoriesResponse,
    OptionSearchRequest,
    OptionSearchResponse,
)
from app.schemas.claim_publication import ClaimSearchRequest, ClaimSearchResponse
from app.schemas.external import ProductOffers
from app.schemas.ingredient import IngredientReadResult
from app.schemas.product_video import ProductVideosResponse
from app.services.catalog_option_service import CatalogOptionService, get_catalog_option_service
from app.services.catalog_service import CatalogService, get_catalog_service
from app.services.claim_publication_service import (
    ClaimPublicationService,
    get_claim_publication_service,
)
from app.services.ingredient_service import IngredientService, get_ingredient_service
from app.services.offer_service import OfferService, get_offer_service
from app.services.product_video_service import ProductVideoService, get_product_video_service

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/catalog/categories", response_model=OptionCategoriesResponse)
async def list_option_categories(
    response: Response,
    service: CatalogOptionService = Depends(get_catalog_option_service),
) -> OptionCategoriesResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.categories()


@router.post("/catalog/options/search", response_model=OptionSearchResponse)
async def search_catalog_options(
    search: OptionSearchRequest,
    response: Response,
    service: CatalogOptionService = Depends(get_catalog_option_service),
) -> OptionSearchResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.search(search)


@router.post("/catalog/ingredient-claims/search", response_model=ClaimSearchResponse)
async def search_ingredient_claims(
    search: ClaimSearchRequest,
    response: Response,
    service: ClaimPublicationService = Depends(get_claim_publication_service),
) -> ClaimSearchResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.search(search)


@router.get("/products", response_model=ProductsResponse)
async def list_products(
    response: Response,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=20),
    ids: str | None = Query(default=None, max_length=2000),
    concerns: str | None = Query(default=None, max_length=200),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductsResponse:
    if category and category not in CATEGORIES:
        raise ApiError(400, "Unknown category", "invalid_category")
    id_list = [s.strip() for s in ids.split(",") if s.strip()][:50] if ids else None
    concern_list = sorted({s.strip() for s in concerns.split(",") if s.strip()}) if concerns else []
    if any(c not in CONCERNS for c in concern_list):
        raise ApiError(400, "Unknown skin concern", "invalid_concern")
    query = q.strip()[:80] if q and q.strip() else None
    products = await service.list_products(
        q=query, category=category or None, ids=id_list, concerns=concern_list or None
    )
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


@router.get("/products/{product_id}/ingredients", response_model=IngredientReadResult)
async def get_product_ingredients(
    response: Response,
    product_id: str = Path(min_length=1, max_length=128),
    shade_id: str | None = Query(default=None, alias="shadeId", min_length=1, max_length=128),
    option_id: str | None = Query(default=None, alias="optionId", min_length=1, max_length=128),
    ingredient_name: str | None = Query(
        default=None, alias="ingredientName", min_length=1, max_length=500
    ),
    operator: Literal["includes", "excludes"] = "includes",
    service: IngredientService = Depends(get_ingredient_service),
) -> IngredientReadResult:
    response.headers["Cache-Control"] = "no-store"
    return await service.get_ingredients(product_id, shade_id, option_id, ingredient_name, operator)


@router.get("/products/{product_id}/offers", response_model=ProductOffers)
async def get_product_offers(
    product_id: str, response: Response, service: OfferService = Depends(get_offer_service)
) -> ProductOffers:
    try:
        result = await service.get_product_offers(product_id)
    except UpstreamError as exc:
        raise ApiError(502, "Shopping search is temporarily unavailable", "upstream_error") from exc
    if result is None:
        raise ApiError(404, "Product not found", "not_found")
    if result.configured:
        cache_for(response, 1800)
    return result


@router.get("/products/{product_id}/videos", response_model=ProductVideosResponse)
async def get_product_videos(
    product_id: str,
    response: Response,
    service: CatalogService = Depends(get_catalog_service),
    videos: ProductVideoService = Depends(get_product_video_service),
) -> ProductVideosResponse:
    if await service.get_product(product_id) is None:
        raise ApiError(404, "Product not found", "not_found")
    result = await videos.videos_for_product(product_id)
    cache_for(response, 300)
    return ProductVideosResponse(videos=result)


@router.get("/offers/search", response_model=ProductOffers)
async def search_offers(
    request: Request,
    response: Response,
    q: str | None = Query(default=None),
    service: OfferService = Depends(get_offer_service),
    limiter: RateLimiter = Depends(get_offer_search_rate_limiter),
) -> ProductOffers:
    query = (q or "").strip()
    if not query:
        raise ApiError(400, "Missing query", "missing_query")
    if not await limiter.allow(client_key(request)):
        raise ApiError(429, "Too many searches. Please wait a moment.", "rate_limited")
    try:
        result = await service.search_offers(query)
    except UpstreamError as exc:
        raise ApiError(502, "Shopping search is temporarily unavailable", "upstream_error") from exc
    if result.configured:
        cache_for(response, 1800)
    return result


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
