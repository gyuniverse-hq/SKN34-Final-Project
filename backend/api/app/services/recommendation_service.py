from fastapi import Depends

from app.schemas.recommendation import (
    SkinRecommendationMatch,
    SkinRecommendationRequest,
    SkinRecommendationResponse,
)
from app.services.catalog_service import CONCERN_TAGS, CatalogService, get_catalog_service


class RecommendationService:
    """Baseline ranking over catalog care tags; no learned or grade-based weights."""

    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def recommend(self, req: SkinRecommendationRequest) -> SkinRecommendationResponse:
        if not req.concerns:
            return SkinRecommendationResponse(concerns=[], status="no_concerns", matches=[])

        # Rank independently of shopping/image providers; use catalog images or the placeholder.
        products = await self._catalog.list_products(with_images=False)
        if not products:
            return SkinRecommendationResponse(
                concerns=req.concerns, status="empty_catalog", matches=[]
            )

        matches: list[SkinRecommendationMatch] = []
        for product in products:
            if product.category not in ("skincare", "suncare"):
                continue
            tags = set(product.tags)
            matched = [c for c in req.concerns if tags.intersection(CONCERN_TAGS[c])]
            if matched:
                matches.append(
                    SkinRecommendationMatch(
                        product=product, matched_concerns=matched, score=len(matched)
                    )
                )
        # Break ties by ID regardless of import order. Do not fill gaps with unrelated items.
        matches.sort(key=lambda match: (-match.score, match.product.id))
        return SkinRecommendationResponse(
            concerns=req.concerns,
            status="ok" if matches else "no_matches",
            matches=matches[: req.limit],
        )


def get_recommendation_service(
    catalog: CatalogService = Depends(get_catalog_service),
) -> RecommendationService:
    return RecommendationService(catalog)
