"""Read the API-owned skincare recommendations over HTTP."""

import httpx
from pydantic import ValidationError

from app.core.errors import UpstreamError
from app.schemas.skincare_recommendation import SkincareRecommendation


class SkincareRecommendationClient:
    def __init__(self, base_url: str, timeout: float = 15) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def recommend(self, body: dict) -> SkincareRecommendation:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._base + "/api/recommendations/skincare/v4", json=body
                )
            response.raise_for_status()
            return SkincareRecommendation.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise UpstreamError("Skincare recommendation request failed") from exc
