"""Call the actual existing AI-tab API; never substitute a locally invented V1."""

import httpx


async def fetch_v1(base_url: str, request: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            base_url.rstrip("/") + "/api/recommendations/skincare",
            json=request,
        )
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("matches"), list):
        raise ValueError("invalid_v1_response")
    for match in body["matches"]:
        if (
            not isinstance(match, dict)
            or not isinstance(match.get("optionId"), str)
            or not isinstance(match.get("product"), dict)
            or not isinstance(match["product"].get("id"), str)
        ):
            raise ValueError("invalid_v1_match")
    return body
