"""Chatbot access to the API-owned G5 index and original passages."""

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.errors import UpstreamError
from app.schemas.knowledge import Location, NeighborResult, SearchResult

_neighbors = TypeAdapter(list[NeighborResult])


class KnowledgeClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def search(self, question, strategy):
        try:
            response = await self.http.post(
                "search", json={"question": question, "strategy": strategy, "limit": 20}
            )
            response.raise_for_status()
            return SearchResult.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UpstreamError("Knowledge search unavailable") from exc

    async def context(self, locations: list[Location]):
        try:
            response = await self.http.post(
                "context",
                json={"evidence": [loc.model_dump(by_alias=True) for loc in locations]},
            )
            response.raise_for_status()
            found = _neighbors.validate_python(response.json())
            if [item.source for item in found] != locations:
                raise ValueError("Knowledge original identity mismatch")
            return found
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise UpstreamError("Knowledge original unavailable") from exc
