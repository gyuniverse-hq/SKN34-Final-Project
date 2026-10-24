import logging

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.errors import ApiError, UpstreamError
from app.core.http import cache_for
from app.core.ratelimit import RateLimiter, client_key, get_tutorial_rate_limiter
from app.schemas.external import YoutubeSearchResult
from app.services.tutorial_service import TutorialService, get_tutorial_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/youtube", tags=["tutorials"])


def _max_results(raw: str | None) -> int:
    try:
        value = int(raw) if raw else 8
    except ValueError:
        value = 8
    return min(max(value or 8, 1), 12)


@router.get("/search", response_model=YoutubeSearchResult)
async def search(
    request: Request,
    response: Response,
    q: str | None = Query(default=None),
    max: str | None = Query(default=None),
    service: TutorialService = Depends(get_tutorial_service),
    limiter: RateLimiter = Depends(get_tutorial_rate_limiter),
) -> YoutubeSearchResult:
    query = (q or "").strip()[:80]
    if not query:
        raise ApiError(400, "Missing query", "missing_query")
    if not service.configured:
        return YoutubeSearchResult(configured=False, videos=[])
    if not await limiter.allow(client_key(request)):
        raise ApiError(429, "Too many searches. Please wait a moment.", "rate_limited")
    try:
        videos = await service.search(query, _max_results(max))
    except UpstreamError as exc:
        logger.warning("tutorial search failed")
        raise ApiError(502, "Tutorial search is temporarily unavailable", "upstream_error") from exc
    cache_for(response, 3600)
    return YoutubeSearchResult(configured=True, videos=videos)
